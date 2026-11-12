// ============================================================
// 会话列表全局 Store（单一数据源）
// - 应用根部常驻：统一订阅 WS 下行事件与跨屏总线
// - 所有影响会话列表实体的变更集中在此：写本地缓存 + 通知订阅者
// - 会话列表页只需订阅本 Store，即可在活跃时及时刷新 UI
//
// 职责边界：
//   这里只处理「会影响会话列表实体 / 本地缓存」的事件；
//   聊天详情页的输入框锁定、发送态等当前任务 UI 状态仍留在详情页。
// ============================================================
import type { MockConversation } from '@/mock/data';
import { hasConversationProactiveHint } from '@/mock/data';
import type { ConnectionState, IMGatewayEvent } from '@/core/im';
import { getAgentId, getChatService, getTenantId } from '@/core/im';
import { getAgentIdFromAuth, getRole } from '@/core/auth';
import { emitDutyState, loadDutyState, saveDutyState } from '@/core/duty';
import { dutyOn, dutyStatus, fetchClaimedTasks } from '@/api/tasks';
import { sortTasksByLastTriggerMsgTime, taskToConversation } from '@/lib/task-session-list';
import {
  buildSeedTestConversations,
  shouldSeedTestConversations,
} from '@/lib/seed-test-conversations';
import {
  discardIfStaleAiReviewRequired,
  pickConversationLastServerMsgID,
} from '@/lib/ai-review-freshness';
import {
  clearClaimedConversationsCache,
  consumeAnnotationEventForCache,
  loadClaimedConversationsCache,
  scheduleMutateClaimedConversationsCache,
  scheduleReplaceClaimedConversationsCache,
  type ClaimedConversationsScope,
} from '@/lib/claimed-conversations-cache';
import {
  buildClaimedUIList,
  findConversationIndexByIdentity,
  mergeClaimedConversations,
  preserveEphemeralLocalFields,
} from '@/lib/claimed-conversations-merge';
import {
  applyAnnotationEventToConversations,
  applyAdoptionContextToConversations,
  applyHandledAdoptionIDToConversations,
  applyLastMessageToConversations,
  applyInactiveToConversations,
  applyTaskClaimedToConversations,
  applyTaskModeToConversations,
  clearConversationRedDot,
  clearProactiveActionHintsFromConversations,
  setProactiveActionHintsOnConversation,
  pickValidAdoptionContext,
} from '@/lib/annotation-event-list';
import type { AdoptionContext, TaskMode, ProactiveActionHint } from '@/core/im/types';
import {
  AnnotationTaskSource,
  ANNOTATION_TASK_SOURCE_LABEL,
} from '@/core/im/types';
import {
  applyReturnedToAgentToConversations,
  applySupervisorTakeoverToConversations,
  scheduleReturnedToAgentCache,
  upsertConversation,
} from '@/lib/supervisor-takeover';
import { subscribeConversationProcessed } from '@/lib/conversation-processed-bus';
import {
  scheduleConversationLastMessage,
  subscribeConversationLastMessage,
  type ConversationLastMessagePayload,
} from '@/lib/conversation-last-message-bus';
import { appAlert } from '@/lib/app-alert';
import { formatTransferErrorCode } from '@/features/conversations/transfer-agent';

// ---- Store 内部状态 ----
let scope: ClaimedConversationsScope | null = null;
let list: MockConversation[] = [];
/** 上一次 commit 后的快照：用于 claimed/list 等全量写回时回填黄点/复审 */
let lastCommittedList: MockConversation[] = [];
/** 最近一次 claimed/list 返回的 claimedCount（导航栏「会话数量」） */
let claimedCount = 0;
let hydrated = false;
let hydrating: Promise<void> | null = null;

/** 允许主动清除 ephemeral 的 commit reason（不从 lastCommitted 回填） */
const DROP_EPHEMERAL_COMMIT_REASONS = new Set([
  'proactive_action_hints_cleared',
  'annotation_event_task_removed',
  'complete_task_result',
  'adoption_handled',
]);

type ListListener = (list: MockConversation[]) => void;
const listListeners = new Set<ListListener>();

/** 单个会话（按 imConversationID）缓存变更监听；prev 为变更前快照（不存在则为 undefined） */
type ConversationChangeListener = (
  conv: MockConversation | undefined,
  prev: MockConversation | undefined,
) => void;
const conversationChangeListeners = new Map<string, Set<ConversationChangeListener>>();

/** 客服被主管接管：需要弹窗提示的信息 */
export type SupervisorTakeoverAlert = {
  taskID?: string;
  imConversationID?: string;
  actorName: string;
  audienceName: string;
};
type TakeoverListener = (info: SupervisorTakeoverAlert) => void;
const takeoverListeners = new Set<TakeoverListener>();

// ---- 生命周期 ----
let started = false;
let disposeFns: Array<() => void> = [];

// ---- 刷新/节流 ----
let refreshInFlight: Promise<void> | null = null;
let lastClaimedRefreshAt = 0;
let lastTakeoverAlertAt = 0;
const CLAIMED_REFRESH_THROTTLE_MS = 1000;
/**
 * 手动操作（接管/归还/上报/认领等）触发任务流转后，claimed/list 落库可能滞后。
 * 统一同步策略：每 0.5s 拉一次，按谓词判定数据是否正确；最多 5 次，超限视为同步超时。
 */
const CLAIMED_SYNC_DELAY_MS = 500;
const CLAIMED_SYNC_MAX_ATTEMPTS = 5;
/** 同步窗口内，保护本地 upsert 不被 merge 成 inactive */
const TAKEOVER_MERGE_GRACE_MS = CLAIMED_SYNC_DELAY_MS * CLAIMED_SYNC_MAX_ATTEMPTS + 5_000;
const TAKEOVER_ALERT_THROTTLE_MS = 1500;
/** key → 宽限截止时间；key 形如 task:xxx / im:xxx */
const pendingTakeoverUntil = new Map<string, number>();
/** 最近一次 claimed/list 返回的 imConversationID / taskID 集合（用于同步判定） */
let lastClaimedRemoteImIds = new Set<string>();
let lastClaimedRemoteTaskIds = new Set<string>();
/** 会话全部置灰后是否已同步过 duty/status（出现活跃会话后重置） */
let allInactiveDutySynced = false;
let dutyRefreshInFlight: Promise<void> | null = null;
/** 活跃从 0→有 后是否已同步过 duty/status（回到 0 后重置） */
let becameActiveDutySynced = false;
let lastSeenActiveCount = -1;
/** 本次登录后是否出现过活跃会话（用于区分「从未接过会话」与「全部被回收后列表为空」） */
let hadActiveConversations = false;
let pendingDutyRefreshReason: 'inactive' | 'active' | null = null;
/** WS 是否曾成功 connected（用于区分首连 / 重连） */
let wsEverConnected = false;
let lastWsConnectionState: ConnectionState | null = null;
let dutyAfterReconnectInFlight: Promise<void> | null = null;

function countActiveClaimedConversations(conversations: MockConversation[]): number {
  return conversations.filter((c) => !c.inactive).length;
}

function requestDutyStatusRefresh(reason: 'inactive' | 'active'): void {
  if (dutyRefreshInFlight) {
    pendingDutyRefreshReason = reason;
    return;
  }
  const agentId = getAgentId();
  if (!agentId) return;

  dutyRefreshInFlight = (async () => {
    try {
      console.log('[ClaimedStore] 刷新 agents/duty/status', {
        reason,
        active: lastSeenActiveCount,
      });
      const st = await dutyStatus(agentId, getTenantId()).catch(() => null);
      if (st?.ok) {
        if (reason === 'inactive') allInactiveDutySynced = true;
        if (reason === 'active') becameActiveDutySynced = true;
        await saveDutyState(agentId, st.on_duty);
        emitDutyState(st.on_duty);
        console.log('[ClaimedStore] agents/duty/status 已同步', { on_duty: st.on_duty, reason });
      }
    } finally {
      dutyRefreshInFlight = null;
      const pending = pendingDutyRefreshReason;
      pendingDutyRefreshReason = null;
      if (pending) requestDutyStatusRefresh(pending);
    }
  })();
}

/**
 * 客服端：活跃会话 0↔有 时拉 agents/duty/status。
 * - 全部置灰 / 曾有活跃后列表被清空：刷下班态
 * - 活跃从无到有：刷上班态
 */
function maybeRefreshDutyWhenAllInactive(conversations: MockConversation[]): void {
  if (getRole() === 'supervisor') return;
  const agentId = getAgentId();
  if (!agentId) return;

  const activeCount = countActiveClaimedConversations(conversations);
  const prevActive = lastSeenActiveCount;
  lastSeenActiveCount = activeCount;

  if (activeCount > 0) {
    hadActiveConversations = true;
    allInactiveDutySynced = false;
    const becameActive = prevActive === 0;
    if (!becameActive || becameActiveDutySynced) return;
    requestDutyStatusRefresh('active');
    return;
  }

  becameActiveDutySynced = false;
  const recycledToEmpty = hadActiveConversations && conversations.length === 0;
  if (conversations.length === 0 && !recycledToEmpty) return;
  if (allInactiveDutySynced) return;
  requestDutyStatusRefresh('inactive');
}

/**
 * WS 重连后对齐上下班状态。
 * - 客服：服务端可能在断线过久后自动下班并回收任务；duty 有变化时再拉 claimed/list。
 * - 主管：保持「永久上班」；若为下班则补 duty/on，并刷新 claimed/list。
 */
async function syncDutyAndClaimedOnWsReconnect(): Promise<void> {
  const agentId = getAgentId();
  if (!agentId) return;
  if (dutyAfterReconnectInFlight) return dutyAfterReconnectInFlight;

  const isSupervisor = getRole() === 'supervisor';

  dutyAfterReconnectInFlight = (async () => {
    try {
      const prevOnDuty = await loadDutyState(agentId);
      console.log('[ClaimedStore] WS 重连，刷新 agents/duty/status', {
        prevOnDuty,
        role: isSupervisor ? 'supervisor' : 'agent',
      });
      const st = await dutyStatus(agentId, getTenantId()).catch(() => null);
      if (!st?.ok) {
        console.warn('[ClaimedStore] WS 重连后 duty/status 失败，跳过');
        return;
      }

      // 主管：下班则补上班，保持在岗
      if (isSupervisor) {
        if (st.on_duty === false) {
          console.log('[ClaimedStore] 主管处于下班态，补调 duty/on');
          const res = await dutyOn(agentId, getTenantId()).catch(() => null);
          if (!res?.ok) {
            console.warn('[ClaimedStore] 主管补调 duty/on 失败，跳过');
            return;
          }
          await saveDutyState(agentId, res.on_duty);
          emitDutyState(res.on_duty);
          await refreshClaimedConversations();
          return;
        }
        await saveDutyState(agentId, true);
        if (prevOnDuty !== true) emitDutyState(true);
        console.log('[ClaimedStore] 主管已在岗，跳过 duty/on');
        return;
      }

      await saveDutyState(agentId, st.on_duty);
      if (st.on_duty === prevOnDuty) {
        console.log('[ClaimedStore] duty 状态未变，跳过 claimed/list', { on_duty: st.on_duty });
        return;
      }

      emitDutyState(st.on_duty);
      console.log('[ClaimedStore] duty 状态变化，刷新 claimed/list', {
        from: prevOnDuty,
        to: st.on_duty,
      });
      await refreshClaimedConversations();
    } catch (e) {
      console.warn('[ClaimedStore] syncDutyAndClaimedOnWsReconnect failed', e);
    } finally {
      dutyAfterReconnectInFlight = null;
    }
  })();

  return dutyAfterReconnectInFlight;
}

function computeScope(): ClaimedConversationsScope | null {
  // 只用登录态里的 agent_id，避免刷新时 IM 环境默认值抢先 hydrate 成空/错缓存
  const agentId = (getAgentIdFromAuth() || getAgentId() || '').trim();
  if (!agentId) return null;
  const role = getRole() === 'supervisor' ? 'supervisor' : 'agent';
  const tenantId = (getTenantId() || agentId).trim() || agentId;
  return { tenantId, role, agentId };
}

function scopeEqual(a: ClaimedConversationsScope | null, b: ClaimedConversationsScope | null): boolean {
  if (!a || !b) return a === b;
  return a.tenantId === b.tenantId && a.role === b.role && a.agentId === b.agentId;
}

function notifyList(): void {
  const snapshot = list;
  for (const l of listListeners) {
    try {
      l(snapshot);
    } catch {
      // 单个订阅者异常不影响其他订阅者
    }
  }
  maybeRefreshDutyWhenAllInactive(snapshot);
}

/**
 * 会话归属/置灰门禁签名：inactive / returnedToAgent / supervisorTakeover / 是否存在。
 */
function ownershipGateSignature(c: MockConversation | undefined): string {
  if (!c) return 'absent';
  return [
    c.inactive ? '1' : '0',
    c.returnedToAgent ? '1' : '0',
    c.supervisorTakeover ? '1' : '0',
  ].join(':');
}

/** 单会话订阅用：归属 + 聊天页需跟进的展示/提示字段 */
function conversationSubscribeSignature(c: MockConversation | undefined): string {
  if (!c) return 'absent';
  const adoption = pickValidAdoptionContext(c.adoptionContext);
  const hintIds =
    c.proactiveActionHints
      ?.map((h) => h.occurrenceKey?.trim() || h.scheduledTaskID?.trim() || '')
      .filter(Boolean)
      .join(',') ?? '';
  return [
    ownershipGateSignature(c),
    c.hasRedDot ? '1' : '0',
    c.skillGroup?.trim() ?? '',
    adoption?.adoptionID?.trim() ?? '',
    c.handledAdoptionID?.trim() ?? '',
    hintIds,
    c.preview ?? '',
    c.time ?? '',
    c.taskMode ?? '',
    String(c.unread ?? 0),
    c.lastMessage?.serverMsgID?.trim() ?? '',
  ].join('|');
}

type OtherConvIndicatorExclude = { taskID?: string; imConversationID?: string };
type OtherConvIndicatorFlags = { hasRedDot: boolean; hasYellowDot: boolean };
type OtherConvIndicatorListener = (flags: OtherConvIndicatorFlags) => void;

let otherConvIndicatorSubId = 0;
const otherConvIndicatorSubs = new Map<
  number,
  {
    exclude: OtherConvIndicatorExclude;
    cb: OtherConvIndicatorListener;
    last: OtherConvIndicatorFlags;
  }
>();

function computeOtherConvIndicators(exclude: OtherConvIndicatorExclude): OtherConvIndicatorFlags {
  return {
    hasRedDot: hasVisibleConversationRedDot(list, exclude),
    hasYellowDot: hasVisibleConversationProactiveHint(list, exclude),
  };
}

function notifyOtherConversationIndicators(): void {
  if (otherConvIndicatorSubs.size === 0) return;
  for (const sub of otherConvIndicatorSubs.values()) {
    const next = computeOtherConvIndicators(sub.exclude);
    if (next.hasRedDot === sub.last.hasRedDot && next.hasYellowDot === sub.last.hasYellowDot) {
      continue;
    }
    sub.last = next;
    try {
      sub.cb(next);
    } catch {
      // ignore
    }
  }
}

function applySeedTestConversationsIfNeeded(): boolean {
  if (!shouldSeedTestConversations()) return false;
  const seeded = buildClaimedUIList(buildSeedTestConversations());
  list = seeded;
  lastCommittedList = seeded;
  claimedCount = countActiveClaimedConversations(seeded);
  notifyList();
  notifyOtherConversationIndicators();
  console.log('[ClaimedStore] 已注入测试接待者/会话', { count: seeded.length });
  return true;
}

/**
 * 订阅「除当前会话外」是否还有可见红/黄点（聊天页返回键提示）。
 * commit 时按 exclude 重算，仅变化时回调。
 */
export function subscribeOtherConversationIndicators(
  exclude: OtherConvIndicatorExclude,
  cb: OtherConvIndicatorListener,
): () => void {
  const id = ++otherConvIndicatorSubId;
  const last = computeOtherConvIndicators(exclude);
  otherConvIndicatorSubs.set(id, { exclude, cb, last });
  try {
    cb(last);
  } catch {
    // ignore
  }
  return () => {
    otherConvIndicatorSubs.delete(id);
  };
}

/** 对比前后两版列表，按 imConversationID 通知单会话订阅者 */
function notifyConversationChange(
  prevList: MockConversation[],
  nextList: MockConversation[],
): void {
  if (conversationChangeListeners.size === 0) return;
  const prevById = new Map<string, MockConversation>();
  for (const c of prevList) {
    const id = c.imConversationID?.trim();
    if (id) prevById.set(id, c);
  }
  const nextById = new Map<string, MockConversation>();
  for (const c of nextList) {
    const id = c.imConversationID?.trim();
    if (id) nextById.set(id, c);
  }
  const changed = new Set<string>();
  for (const [id, next] of nextById) {
    const prev = prevById.get(id);
    if (conversationSubscribeSignature(prev) !== conversationSubscribeSignature(next)) {
      changed.add(id);
    }
  }
  for (const [id] of prevById) {
    if (!nextById.has(id)) changed.add(id);
  }
  if (changed.size === 0) return;
  for (const id of changed) {
    const set = conversationChangeListeners.get(id);
    if (!set) continue;
    const conv = nextById.get(id);
    const prev = prevById.get(id);
    for (const cb of set) {
      try {
        cb(conv, prev);
      } catch {
        // 单个订阅者异常不影响其他
      }
    }
  }
}

function emitTakeover(info: SupervisorTakeoverAlert): void {
  for (const l of takeoverListeners) {
    try {
      l(info);
    } catch {
      // ignore
    }
  }
}

/** 逐项引用相等（mergeOne 已保证内容未变时复用原对象） */
function isSameListContent(a: MockConversation[], b: MockConversation[]): boolean {
  if (a === b) return true;
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) return false;
  }
  return true;
}

/** 写缓存（全量替换）+ 通知 UI；统一按 lastMessage 时间重排，避免增量 bump 导致顺序漂移 */
function commit(reason: string): void {
  // 以上一次 commit 的快照为对比基准（handler 已在 commit 前修改 list，
  // 直接取 list 会丢掉真正的内容变化，导致 per-imConversationID 订阅不触发）
  const prevList = lastCommittedList;
  list = buildClaimedUIList(list);

  // claimed/list / 并发写回可能丢掉接口不返回的黄点：非主动清除时从上一版回填
  if (!DROP_EPHEMERAL_COMMIT_REASONS.has(reason) && lastCommittedList.length > 0) {
    const restored = preserveEphemeralLocalFields(lastCommittedList, list);
    if (restored !== list) {
      const lostHints = lastCommittedList.filter(
        (c) =>
          !!c.proactiveActionHints?.length &&
          !restored.find(
            (x) =>
              ((c.imConversationID && x.imConversationID === c.imConversationID) || x.id === c.id) &&
              !!x.proactiveActionHints?.length,
          ),
      );
      if (lostHints.length) {
        console.warn('[ClaimedStore] commit 回填后仍有黄点丢失', {
          reason,
          taskIDs: lostHints.map((c) => c.id),
        });
      } else {
        console.log('[ClaimedStore] commit 已回填 ephemeral（含 proactiveActionHints）', { reason });
      }
      list = restored;
    }
  }

  // 主动清除时打印，便于区分「莫名清空」与用户/任务回收
  if (DROP_EPHEMERAL_COMMIT_REASONS.has(reason)) {
    console.log('[ClaimedStore] commit 主动清除 ephemeral', { reason });
  }

  // 内容逐项未变（claimed/list 轮询的常态）：复用上一版数组，让订阅方 setState 直接 bail out，
  // 同时跳过写盘的整表 JSON 序列化
  const unchanged = isSameListContent(lastCommittedList, list);
  if (unchanged) {
    list = lastCommittedList;
  }

  lastCommittedList = list;
  if (scope && !unchanged) scheduleReplaceClaimedConversationsCache(scope, list, reason);
  notifyList();
  notifyOtherConversationIndicators();
  notifyConversationChange(prevList, list);
}

/**
 * 确保已按当前登录态 hydrate。
 * 登录态（tenant/role/agent）变化时会重置并重新从缓存加载。
 */
export async function ensureClaimedConversationsHydrated(): Promise<void> {
  const next = computeScope();
  if (!next) return;
  if (!scopeEqual(scope, next)) {
    scope = next;
    hydrated = false;
    hydrating = null;
    list = [];
    lastCommittedList = [];
    claimedCount = 0;
    allInactiveDutySynced = false;
    becameActiveDutySynced = false;
    lastSeenActiveCount = -1;
    hadActiveConversations = false;
    pendingDutyRefreshReason = null;
  }
  if (hydrated) return;
  if (!hydrating) {
    hydrating = (async () => {
      const startedAt = Date.now();
      console.log('[ClaimedStore] 开始 hydrate 本地会话缓存', { scope: scope! });
      const cached = await loadClaimedConversationsCache(scope!);
      list = buildClaimedUIList(cached);
      lastCommittedList = list;
      if (claimedCount === 0) {
        claimedCount = countActiveClaimedConversations(list);
      }
      hydrated = true;
      hydrating = null;
      console.log('[ClaimedStore] hydrate 本地会话缓存完成', {
        scope: scope!,
        elapsedMs: Date.now() - startedAt,
        cacheCount: cached.length,
        uiCount: list.length,
        claimedCount,
      });
      if (list.length === 0) applySeedTestConversationsIfNeeded();
      else notifyList();
    })();
  }
  await hydrating;
}

/** 当前会话列表快照（未 hydrate 时为空数组） */
export function getClaimedConversationsSnapshot(): MockConversation[] {
  return list;
}

/** 最近一次 claimed/list 的 claimedCount（未拉过接口时为 0） */
export function getClaimedCountSnapshot(): number {
  return claimedCount;
}

/**
 * 清空本地会话列表缓存（内存 + AsyncStorage）。
 * 不自动拉取 claimed/list；聊天页下次进入/下拉刷新后再合并。
 */
export async function clearLocalClaimedConversations(
  reason = 'manual_clear',
): Promise<void> {
  await ensureClaimedConversationsHydrated();
  list = [];
  lastCommittedList = [];
  claimedCount = 0;
  notifyList();
  if (scope) {
    await clearClaimedConversationsCache(scope, reason);
  }
}

/**
 * 仅清除置灰（inactive）会话，保留活跃会话。
 * 返回被清除会话的 imConversationID（用于同步清聊天消息缓存）。
 */
export async function clearInactiveClaimedConversations(
  reason = 'manual_clear_inactive',
): Promise<string[]> {
  await ensureClaimedConversationsHydrated();
  const inactive = list.filter((c) => c.inactive);
  const imIds = inactive
    .map((c) => c.imConversationID?.trim() || '')
    .filter(Boolean);
  if (inactive.length === 0) {
    console.log('[ClaimedStore] 无置灰会话可清除', { reason });
    return [];
  }
  list = list.filter((c) => !c.inactive);
  commit(reason);
  console.log('[ClaimedStore] 已清除置灰会话', {
    reason,
    removed: inactive.length,
    kept: list.length,
    imConversationIDs: imIds,
  });
  return imIds;
}

/**
 * 删除单条置灰会话（活跃会话拒绝删除）。
 * 返回被删会话的 imConversationID（无则空串），未删除时返回 null。
 */
export async function removeInactiveClaimedConversation(
  match: Pick<MockConversation, 'imConversationID' | 'id'>,
  reason = 'manual_remove_inactive',
): Promise<string | null> {
  await ensureClaimedConversationsHydrated();
  const idx = findConversationIndexByIdentity(list, match);
  if (idx < 0) {
    console.log('[ClaimedStore] 单条删除：未找到会话', { reason, match });
    return null;
  }
  const target = list[idx];
  if (!target.inactive) {
    console.warn('[ClaimedStore] 拒绝删除活跃会话', { reason, match });
    return null;
  }
  const imId = target.imConversationID?.trim() || '';
  list = list.filter((_, i) => i !== idx);
  commit(reason);
  console.log('[ClaimedStore] 已删除单条置灰会话', {
    reason,
    imConversationID: imId || undefined,
    taskID: target.id,
    kept: list.length,
  });
  return imId;
}

/**
 * 删除满足条件的置灰会话（活跃会话一律保留）。
 * 返回实际删除项的 imConversationID / taskID，供清消息缓存与关闭已打开的聊天窗。
 */
export async function removeInactiveClaimedConversationsMatching(
  match: (c: MockConversation) => boolean,
  reason = 'manual_remove_inactive_matching',
): Promise<{ imConversationIDs: string[]; taskIDs: string[] }> {
  await ensureClaimedConversationsHydrated();
  const removed = list.filter((c) => c.inactive && match(c));
  if (removed.length === 0) {
    console.log('[ClaimedStore] 批量删除：无匹配置灰会话', { reason });
    return { imConversationIDs: [], taskIDs: [] };
  }
  const removedKeys = new Set(removed);
  list = list.filter((c) => !removedKeys.has(c));
  commit(reason);
  const imConversationIDs = Array.from(
    new Set(removed.map((c) => c.imConversationID?.trim() || '').filter(Boolean)),
  );
  const taskIDs = Array.from(
    new Set(removed.map((c) => c.id?.trim() || '').filter(Boolean)),
  );
  console.log('[ClaimedStore] 已批量删除置灰会话', {
    reason,
    removed: removed.length,
    kept: list.length,
    imConversationIDs,
    taskIDs,
  });
  return { imConversationIDs, taskIDs };
}

/**
 * 是否存在「可见」红点会话（与会话列表 UI 一致：置灰会话不计入）。
 * exclude：聊天详情页排除当前会话，只提示其它会话的红点。
 */
export function hasVisibleConversationRedDot(
  conversations: MockConversation[],
  exclude?: { taskID?: string; imConversationID?: string },
): boolean {
  return conversations.some((c) => {
    if (!c.hasRedDot || c.inactive) return false;
    if (exclude?.imConversationID && c.imConversationID === exclude.imConversationID) return false;
    if (exclude?.taskID && c.id === exclude.taskID) return false;
    return true;
  });
}

/**
 * 是否存在「可见」黄点会话（主动触达提醒；置灰不计入）。
 * exclude：聊天详情页排除当前会话，只提示其它会话的黄点。
 */
export function hasVisibleConversationProactiveHint(
  conversations: MockConversation[],
  exclude?: { taskID?: string; imConversationID?: string },
): boolean {
  return conversations.some((c) => {
    if (c.inactive || !hasConversationProactiveHint(c)) return false;
    if (exclude?.imConversationID && c.imConversationID === exclude.imConversationID) return false;
    if (exclude?.taskID && c.id === exclude.taskID) return false;
    return true;
  });
}

/** 订阅会话列表变化；订阅即回推一次当前快照（已 hydrate 时） */
export function subscribeClaimedConversations(cb: ListListener): () => void {
  listListeners.add(cb);
  if (hydrated) {
    try {
      cb(list);
    } catch {
      // ignore
    }
  }
  return () => {
    listListeners.delete(cb);
  };
}

/**
 * 订阅「指定 imConversationID 缓存内容变化」（含被移除）。
 * 统一封装：各功能（聊天页刷新数据/权限等）按需调用，避免各自重复 diff 全量列表。
 * @param opts.emitInitial 默认 true：订阅即回推一次当前快照；进房初始化已拉 detail 时可传 false，避免重复请求
 */
export function subscribeConversationChange(
  imConversationID: string,
  cb: ConversationChangeListener,
  opts?: { emitInitial?: boolean },
): () => void {
  const id = imConversationID?.trim();
  if (!id) return () => {};
  let set = conversationChangeListeners.get(id);
  if (!set) {
    set = new Set<ConversationChangeListener>();
    conversationChangeListeners.set(id, set);
  }
  set.add(cb);
  if (hydrated && opts?.emitInitial !== false) {
    try {
      const cur = list.find((c) => c.imConversationID?.trim() === id);
      cb(cur, undefined);
    } catch {
      // ignore
    }
  }
  return () => {
    set.delete(cb);
    if (set.size === 0) conversationChangeListeners.delete(id);
  };
}

/** 订阅“会话被主管接管”提示（全局弹窗用） */
export function subscribeSupervisorTakeoverAlert(cb: TakeoverListener): () => void {
  takeoverListeners.add(cb);
  return () => {
    takeoverListeners.delete(cb);
  };
}

/**
 * 拉取 claimed/list 并合并进 Store（写缓存 + 通知）。
 * 每次调用：active 会话的 taskMode / lastMessage / preview 等对齐本次 list；
 * hasRedDot 结合本地 redDotAckServerMsgID 重算（见 mergeClaimedConversations）。
 * 并发去重：进行中的请求会被复用。
 */
export function refreshClaimedConversations(): Promise<void> {
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = (async () => {
    try {
      await ensureClaimedConversationsHydrated();
      if (!scope) return;
      const res = await fetchClaimedTasks();
      const sorted = sortTasksByLastTriggerMsgTime(res?.tasks ?? []);
      const remoteActive = sorted.map((task, idx) => taskToConversation(task, idx));
      if (remoteActive.length === 0 && applySeedTestConversationsIfNeeded()) return;
      claimedCount =
        typeof res?.claimedCount === 'number' && Number.isFinite(res.claimedCount)
          ? Math.max(0, Math.floor(res.claimedCount))
          : remoteActive.length;
      lastClaimedRemoteImIds = new Set(
        remoteActive
          .map((remote) => remote.imConversationID?.trim())
          .filter((id): id is string => !!id),
      );
      lastClaimedRemoteTaskIds = new Set(
        remoteActive
          .map((remote) => remote.id?.trim())
          .filter((id): id is string => !!id),
      );
      // list 已包含接管任务 → 解除宽限，后续以接口为准
      for (const remote of remoteActive) {
        clearPendingTakeover({
          taskID: remote.id,
          imConversationID: remote.imConversationID,
        });
      }
      const merged = mergeClaimedConversations(list, remoteActive);
      // 以 claimed/list 原始任务再次校准 taskMode，避免中间映射或并发缓存更新漏字段。
      const taskModeByKey = new Map<string, TaskMode>();
      for (const task of sorted) {
        if (task.taskMode !== 'human' && task.taskMode !== 'ai_assisted') continue;
        if (task.taskID) taskModeByKey.set(`task:${task.taskID}`, task.taskMode);
        if (task.imConversationID) {
          taskModeByKey.set(`conversation:${task.imConversationID}`, task.taskMode);
        }
        if (task.session?.imConversationID) {
          taskModeByKey.set(`conversation:${task.session.imConversationID}`, task.taskMode);
        }
      }
      let nextList = merged.ui.map((conversation) => {
        const authoritativeTaskMode =
          taskModeByKey.get(`conversation:${conversation.imConversationID ?? ''}`) ??
          taskModeByKey.get(`task:${conversation.id}`);
        return authoritativeTaskMode && conversation.taskMode !== authoritativeTaskMode
          ? { ...conversation, taskMode: authoritativeTaskMode }
          : conversation;
      });
      // 刷新期间 WS 可能已写入黄点/复审上下文，合并回最新内存避免被覆盖
      nextList = preserveEphemeralLocalFields(list, nextList);
      // 接管宽限期内：claimed/list 尚未包含时，勿把本地 upsert 标成 inactive
      nextList = preservePendingTakeoverActive(nextList);
      list = nextList;
      commit('claimed_list_merge');
    } catch (e) {
      // 后台刷新失败保留现有列表，勿冒泡成 Uncaught（如 Failed to fetch）
      console.warn('[ClaimedStore] refreshClaimedConversations failed', e);
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

let lastMessageQueue: ConversationLastMessagePayload[] = [];
let lastMessageFlushing = false;

/** 聊天页末条回写：同一次派发多会话合并为一次 commit，避免列表连闪 */
function enqueueConversationLastMessage(payload: ConversationLastMessagePayload): void {
  lastMessageQueue.push(payload);
  void flushConversationLastMessageQueue();
}

async function flushConversationLastMessageQueue(): Promise<void> {
  if (lastMessageFlushing) return;
  lastMessageFlushing = true;
  try {
    await ensureClaimedConversationsHydrated();
    while (lastMessageQueue.length) {
      const items = lastMessageQueue;
      lastMessageQueue = [];
      const latest = new Map<string, ConversationLastMessagePayload>();
      for (const p of items) {
        const id = p.imConversationID.trim();
        if (id) latest.set(id, p);
      }
      let next = list;
      let changed = false;
      for (const p of latest.values()) {
        const applied = applyLastMessageToConversations(next, p);
        if (applied) {
          next = applied;
          changed = true;
        }
      }
      if (changed) {
        list = next;
        commit('conversation_last_message');
      }
    }
  } finally {
    lastMessageFlushing = false;
    if (lastMessageQueue.length) void flushConversationLastMessageQueue();
  }
}

// ---- WS / 总线事件处理（均写缓存 + 通知） ----

async function handleAnnotationEvent(evt: Extract<IMGatewayEvent, { type: 'annotation_event' }>): Promise<void> {
  // 去重：同一 eventID 只处理一次
  if (consumeAnnotationEventForCache(evt.event?.eventID)) return;
  await ensureClaimedConversationsHydrated();
  const eventType = evt.event?.eventType;

  // 新消息与聊天页回写共用末条防抖窗口，避免分栏页连闪
  if (eventType === 1) {
    const msg = evt.event?.message;
    const imConversationID = evt.task_context?.imConversationID?.trim();
    if (msg && imConversationID) {
      scheduleConversationLastMessage({
        imConversationID,
        lastMessage: {
          ...msg,
          sendTime: msg.sendTime || evt.event?.eventTime || Date.now(),
        },
      });
      return;
    }
  }

  let next = applyAnnotationEventToConversations(list, evt);

  // 内存未命中：从磁盘缓存补丁后必须同步回内存（禁止只写盘，否则后续 commit/replace 会整表抹掉黄点）
  if (next === list && scope && (eventType === 2 || eventType === 3 || eventType === 5 || eventType === 8)) {
    const cached = await loadClaimedConversationsCache(scope);
    const patchedCache = applyAnnotationEventToConversations(cached, evt);
    if (patchedCache !== cached) {
      const match = {
        imConversationID: evt.task_context?.imConversationID,
        id: evt.task_context?.taskID ?? evt.event?.taskID ?? '',
      };
      const idxCache = findConversationIndexByIdentity(patchedCache, match);
      if (idxCache >= 0) {
        const patchedItem = patchedCache[idxCache];
        const idxMem = findConversationIndexByIdentity(list, match);
        if (idxMem >= 0) {
          next = applyAnnotationEventToConversations(list, evt);
          // apply 仍未命中（主键写法不一致）：直接用磁盘补丁行 upsert
          if (next === list) {
            next = upsertConversation(list, patchedItem);
          }
        } else {
          next = upsertConversation(list, patchedItem);
        }
        console.log('[ClaimedStore] annotation_event 磁盘命中后同步回内存', {
          eventType,
          taskID: match.id,
          imConversationID: match.imConversationID,
          hasHints: !!patchedItem.proactiveActionHints?.length,
          hasAdoption: !!pickValidAdoptionContext(patchedItem.adoptionContext),
        });
      }
    }
  }

  if (next !== list) {
    list = next;
    commit(
      eventType === 2 || eventType === 3
        ? 'annotation_event_task_removed'
        : eventType === 5
          ? 'annotation_event_proactive_hint'
          : eventType === 8
            ? 'annotation_event_adoption'
            : 'annotation_event',
    );
  } else if ((eventType === 2 || eventType === 3 || eventType === 5 || eventType === 8) && scope) {
    // 内存+磁盘均未命中：会话尚未进列表，只能先记盘；下次 hydrate/merge 再带上
    const taskID = evt.task_context?.taskID ?? evt.event?.taskID;
    const imConversationID = evt.task_context?.imConversationID;
    console.warn('[ClaimedStore] annotation_event 内存与磁盘均未命中，仅回退写盘', {
      eventType,
      taskID,
      imConversationID,
    });
    scheduleMutateClaimedConversationsCache(
      scope,
      (cached) => {
        const patched = applyAnnotationEventToConversations(cached, evt);
        return patched !== cached ? patched : null;
      },
      eventType === 5
        ? 'annotation_event_proactive_hint'
        : eventType === 8
          ? 'annotation_event_adoption'
          : 'annotation_event_task_removed',
    );
  }

  // 任务回收：与 annotation_task_claimed 对称，拉 claimed/list 直到该会话从活跃列表消失
  if (eventType === 2 || eventType === 3) {
    const match = {
      imConversationID: evt.task_context?.imConversationID,
      taskID: evt.task_context?.taskID ?? evt.event?.taskID,
    };
    if (!match.imConversationID && !match.taskID) return;
    console.log('[ClaimedStore] annotation_event 任务回收，拉取 claimed/list', {
      eventType,
      ...match,
      exists: conversationExists(list, match),
    });
    void syncClaimedList({
      match,
      expect: 'absent',
      tag: 'annotation_event_task_removed',
    });
  }
}

async function handleAiReviewRequired(
  evt: Extract<IMGatewayEvent, { type: 'ai_review_required' }> | Record<string, unknown>,
): Promise<void> {
  if (getRole() === 'supervisor') return;

  const e = evt as any;
  const event = e?.event ?? e?.payload?.event;
  const taskContext = e?.task_context ?? e?.payload?.task_context;

  const annotatorID: string | undefined = event?.annotatorID;
  if (annotatorID && annotatorID !== getAgentId()) return;

  const taskID: string | undefined =
    event?.taskID ?? taskContext?.taskID;
  const imConversationID: string | undefined = taskContext?.imConversationID;
  const lastTriggerMsgID: string | undefined = taskContext?.lastTriggerMsgID;

  await ensureClaimedConversationsHydrated();
  const convLastServerMsgID = pickConversationLastServerMsgID(list, { taskID, imConversationID });
  if (
    discardIfStaleAiReviewRequired(
      { lastTriggerMsgID, convLastServerMsgID, taskID, imConversationID },
      { stage: 'claimed_store', eventID: event?.eventID ?? null },
    )
  ) {
    return;
  }

  // 与 annotation_event 共用 eventID 去重，避免同一次复审双写（过时帧不占用去重）
  if (consumeAnnotationEventForCache(event?.eventID)) return;

  const adoption = pickValidAdoptionContext(event?.adoptionContext);
  if (!adoption || (!taskID && !imConversationID)) return;

  const params = { taskID, imConversationID, adoptionContext: adoption };
  const next = applyAdoptionContextToConversations(list, params);
  if (next) {
    list = next;
    commit('ai_review_required');
    return;
  }
  if (scope) {
    scheduleMutateClaimedConversationsCache(
      scope,
      (cached) => applyAdoptionContextToConversations(cached, params),
      'ai_review_required',
    );
  }
}

async function handleClaimedRefreshEvent(opts?: { bypassThrottle?: boolean }): Promise<void> {
  const now = Date.now();
  if (!opts?.bypassThrottle && now - lastClaimedRefreshAt < CLAIMED_REFRESH_THROTTLE_MS) return;
  lastClaimedRefreshAt = now;
  try {
    await refreshClaimedConversations();
  } catch (e) {
    console.warn('[ClaimedStore] handleClaimedRefreshEvent failed', e);
  }
}

function takeoverPendingKeys(match: { imConversationID?: string; taskID?: string }): string[] {
  const keys: string[] = [];
  if (match.taskID) keys.push(`task:${match.taskID}`);
  if (match.imConversationID) keys.push(`im:${match.imConversationID}`);
  return keys;
}

function markPendingTakeover(match: { imConversationID?: string; taskID?: string }): void {
  const until = Date.now() + TAKEOVER_MERGE_GRACE_MS;
  for (const key of takeoverPendingKeys(match)) {
    pendingTakeoverUntil.set(key, until);
  }
}

function clearPendingTakeover(match: { imConversationID?: string; taskID?: string }): void {
  for (const key of takeoverPendingKeys(match)) {
    pendingTakeoverUntil.delete(key);
  }
}

function isMatchPendingTakeover(match: { imConversationID?: string; taskID?: string }): boolean {
  if (pendingTakeoverUntil.size === 0) return false;
  const now = Date.now();
  let pending = false;
  for (const key of takeoverPendingKeys(match)) {
    const until = pendingTakeoverUntil.get(key);
    if (until == null) continue;
    if (until <= now) {
      pendingTakeoverUntil.delete(key);
      continue;
    }
    pending = true;
  }
  return pending;
}

function isPendingTakeoverConversation(c: MockConversation): boolean {
  return isMatchPendingTakeover({ taskID: c.id, imConversationID: c.imConversationID });
}

/**
 * takeover 落库宽限期内：list 未包含时 merge 会标 inactive，此处临时保留 active，
 * 避免聊天页 upsert 后列表闪灰/消失。
 */
function preservePendingTakeoverActive(
  conversations: MockConversation[],
): MockConversation[] {
  if (pendingTakeoverUntil.size === 0) return conversations;
  let changed = false;
  const next = conversations.map((c) => {
    if (!c.inactive || !isPendingTakeoverConversation(c)) return c;
    changed = true;
    console.log('[ClaimedStore] takeover 宽限期内保留 active（claimed/list 尚未同步）', {
      taskID: c.id,
      imConversationID: c.imConversationID,
    });
    return {
      ...c,
      inactive: false,
      returnedToAgent: false,
      supervisorTakeover: false,
    };
  });
  return changed ? next : conversations;
}

// ---- 统一的 claimed/list 同步：延时轮询直至数据正确 ----

/** 同步谓词：基于本次 claimed/list 返回的 imConversationID / taskID 集合判定数据是否正确 */
type SyncClaimedPredicate = (remote: {
  imIds: Set<string>;
  taskIds: Set<string>;
}) => boolean;

/**
 * 期望的同步方向：
 * - present：会话应出现在自己的 claimed/list（接手方）
 * - absent：会话应从自己的 claimed/list 消失（交出方）
 */
export type SyncClaimedExpect = 'present' | 'absent';

export interface SyncClaimedListOptions {
  match: { imConversationID?: string; taskID?: string };
  /** 同步完成判定方向，默认 present */
  expect?: SyncClaimedExpect;
  /** 轮询间隔，默认 0.5s */
  delayMs?: number;
  /** 最大尝试次数，默认 5 */
  maxAttempts?: number;
  /** 是否对本地 upsert 打宽限期保护（接管类需要） */
  grace?: boolean;
  /** 超时弹窗（不传则不弹） */
  timeoutAlert?: { title: string; message: string };
  /** 日志标签 */
  tag?: string;
}

const syncInFlight = new Map<string, Promise<boolean>>();
const syncCancelTokens = new Map<string, { cancelled: boolean }>();

/** 下班后短轮询：取消令牌（再次上班 / 重复下班时作废） */
let dutyOffSyncToken: { cancelled: boolean } | null = null;
let dutyOffSyncInFlight: Promise<boolean> | null = null;

/**
 * 去重 key 必须带上同步方向：同一次流转会同时收到 *_result 与 ownership_changed，
 * 两者 match 相同但期望方向可能相反，只按会话去重会让先到者把谓词强加给后到者。
 */
function syncMatchKey(
  match: { imConversationID?: string; taskID?: string },
  expect: SyncClaimedExpect,
): string {
  const id = match.imConversationID?.trim() || match.taskID?.trim() || '';
  return id ? `${id}#${expect}` : '';
}

/** 默认谓词：list 包含目标会话 */
function presentInListPredicate(match: {
  imConversationID?: string;
  taskID?: string;
}): SyncClaimedPredicate {
  const imId = match.imConversationID?.trim();
  const taskId = match.taskID?.trim();
  return ({ imIds, taskIds }) =>
    (imId ? imIds.has(imId) : false) || (taskId ? taskIds.has(taskId) : false);
}

/** 反向谓词：list 已不再包含目标会话（被接管/归还后对方侧） */
function absentFromListPredicate(match: {
  imConversationID?: string;
  taskID?: string;
}): SyncClaimedPredicate {
  const imId = match.imConversationID?.trim();
  const taskId = match.taskID?.trim();
  return ({ imIds, taskIds }) =>
    (imId ? !imIds.has(imId) : true) && (taskId ? !taskIds.has(taskId) : true);
}

/**
 * 统一同步 claimed/list：
 * - 每 delayMs 拉一次，按 expect 方向判定数据是否正确；
 * - 命中则 resolve(true)；超过 maxAttempts 仍不满足则 resolve(false)（可选弹超时提示）；
 * - 相同 match + 相同 expect 的并发同步复用同一个 Promise（去重）；
 * - grace=true 时在同步窗口内保护本地 upsert 不被 merge 成 inactive。
 *
 * 各手动动作 handler 应 await 本函数后再做后续本地标记，避免基于未同步的列表状态写缓存。
 */
export function syncClaimedList(opts: SyncClaimedListOptions): Promise<boolean> {
  const match = opts.match;
  const expect: SyncClaimedExpect = opts.expect ?? 'present';
  const key = syncMatchKey(match, expect);
  if (!key) return Promise.resolve(false);

  const existing = syncInFlight.get(key);
  if (existing) return existing;

  const delayMs = opts.delayMs ?? CLAIMED_SYNC_DELAY_MS;
  const maxAttempts = opts.maxAttempts ?? CLAIMED_SYNC_MAX_ATTEMPTS;
  const predicate: SyncClaimedPredicate =
    expect === 'absent' ? absentFromListPredicate(match) : presentInListPredicate(match);
  const tag = opts.tag ?? 'sync';

  if (opts.grace) markPendingTakeover(match);

  const token = { cancelled: false };
  syncCancelTokens.set(key, token);

  const task = (async (): Promise<boolean> => {
    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      if (token.cancelled) {
        console.log('[ClaimedStore] syncClaimedList 已取消', { tag, ...match, attempt });
        if (opts.grace) clearPendingTakeover(match);
        return false;
      }
      await new Promise((resolve) => setTimeout(resolve, delayMs));
      if (token.cancelled) {
        console.log('[ClaimedStore] syncClaimedList 已取消', { tag, ...match, attempt });
        if (opts.grace) clearPendingTakeover(match);
        return false;
      }
      // console.log('[ClaimedStore] syncClaimedList 轮询 claimed/list', {
      //   tag,
      //   ...match,
      //   expect,
      //   attempt,
      //   maxAttempts,
      //   delayMs,
      // });
      await handleClaimedRefreshEvent({ bypassThrottle: true });
      if (predicate({ imIds: lastClaimedRemoteImIds, taskIds: lastClaimedRemoteTaskIds })) {
        if (opts.grace) clearPendingTakeover(match);
        console.log('[ClaimedStore] syncClaimedList 同步完成', { tag, ...match, expect, attempt });
        return true;
      }
    }
    console.warn('[ClaimedStore] syncClaimedList 同步超时', { tag, ...match, expect, maxAttempts });
    if (opts.grace) clearPendingTakeover(match);
    if (opts.timeoutAlert) appAlert(opts.timeoutAlert.title, opts.timeoutAlert.message);
    return false;
  })();

  syncInFlight.set(
    key,
    task.finally(() => {
      syncInFlight.delete(key);
      syncCancelTokens.delete(key);
    }),
  );
  return task;
}

/** 取消并清理所有进行中的同步（登出/释放时调用） */
function cancelAllSyncClaimedList(): void {
  for (const token of syncCancelTokens.values()) token.cancelled = true;
  syncCancelTokens.clear();
  syncInFlight.clear();
  pendingTakeoverUntil.clear();
  cancelSyncClaimedListAfterDutyOff();
}

/** 取消下班后的 claimed/list 短轮询 */
export function cancelSyncClaimedListAfterDutyOff(): void {
  if (dutyOffSyncToken) dutyOffSyncToken.cancelled = true;
  dutyOffSyncToken = null;
  dutyOffSyncInFlight = null;
}

export interface SyncClaimedListAfterDutyOffOptions {
  /** duty/off 返回的回收任务数；有则用「剩余 active ≤ before - reclaimed」判定 */
  reclaimedTaskCount?: number;
  delayMs?: number;
  maxAttempts?: number;
}

/**
 * 下班成功后：短轮询 claimed/list 对账置灰，不依赖 eventType=2。
 * - 立即拉一次，再按 delayMs 重试，最多 maxAttempts 次
 * - 成功条件：本地 active（!inactive）数 ≤ 期望剩余（默认 0）
 * - 重复调用会取消上一次轮询
 */
export function syncClaimedListAfterDutyOff(
  opts?: SyncClaimedListAfterDutyOffOptions,
): Promise<boolean> {
  cancelSyncClaimedListAfterDutyOff();

  const delayMs = opts?.delayMs ?? CLAIMED_SYNC_DELAY_MS;
  const maxAttempts = opts?.maxAttempts ?? CLAIMED_SYNC_MAX_ATTEMPTS;
  const beforeActive = countActiveClaimedConversations(list);
  const reclaimed =
    typeof opts?.reclaimedTaskCount === 'number' && Number.isFinite(opts.reclaimedTaskCount)
      ? Math.max(0, Math.floor(opts.reclaimedTaskCount))
      : undefined;
  const expectedMaxActive =
    reclaimed !== undefined ? Math.max(0, beforeActive - reclaimed) : 0;

  const token = { cancelled: false };
  dutyOffSyncToken = token;

  const task = (async (): Promise<boolean> => {
    console.log('[ClaimedStore] syncClaimedListAfterDutyOff 开始', {
      beforeActive,
      reclaimedTaskCount: reclaimed,
      expectedMaxActive,
      delayMs,
      maxAttempts,
    });

    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      if (token.cancelled) {
        console.log('[ClaimedStore] syncClaimedListAfterDutyOff 已取消', { attempt });
        return false;
      }

      await handleClaimedRefreshEvent({ bypassThrottle: true });
      if (token.cancelled) {
        console.log('[ClaimedStore] syncClaimedListAfterDutyOff 已取消', { attempt });
        return false;
      }

      const active = countActiveClaimedConversations(list);
      console.log('[ClaimedStore] syncClaimedListAfterDutyOff 轮询', {
        attempt,
        maxAttempts,
        active,
        expectedMaxActive,
        remoteTaskCount: lastClaimedRemoteTaskIds.size,
      });

      if (active <= expectedMaxActive) {
        console.log('[ClaimedStore] syncClaimedListAfterDutyOff 同步完成', {
          attempt,
          active,
          expectedMaxActive,
        });
        return true;
      }

      if (attempt < maxAttempts) {
        await new Promise((resolve) => setTimeout(resolve, delayMs));
      }
    }

    console.warn('[ClaimedStore] syncClaimedListAfterDutyOff 同步超时', {
      maxAttempts,
      active: countActiveClaimedConversations(list),
      expectedMaxActive,
    });
    return false;
  })();

  dutyOffSyncInFlight = task.finally(() => {
    if (dutyOffSyncToken === token) {
      dutyOffSyncToken = null;
      dutyOffSyncInFlight = null;
    }
  });
  return dutyOffSyncInFlight;
}

/**
 * 统一解析事件的会话标识。
 * 服务端 task_context 常只带 taskID/threadID，此时用 taskID 从本地反查 imConversationID，
 * 保证同一次流转的多个事件（*_result 与 ownership_changed）产出同一个同步去重 key。
 */
async function resolveConversationMatch(params: {
  taskID?: string;
  imConversationID?: string;
}): Promise<{ taskID?: string; imConversationID?: string }> {
  const taskID = params.taskID?.trim() || undefined;
  let imConversationID = params.imConversationID?.trim() || undefined;
  if (!imConversationID && taskID) {
    await ensureClaimedConversationsHydrated();
    imConversationID = list.find((c) => c.id === taskID)?.imConversationID?.trim() || undefined;
  }
  return { taskID, imConversationID };
}

function conversationExists(
  conversations: MockConversation[],
  match: { imConversationID?: string; taskID?: string },
): boolean {
  if (match.imConversationID) {
    if (conversations.some((c) => c.imConversationID === match.imConversationID)) return true;
  }
  if (match.taskID) {
    if (conversations.some((c) => c.id === match.taskID)) return true;
  }
  return false;
}

/**
 * 新认领任务（annotation_task_claimed）：
 * - status=1（新认领的活跃任务）：无论本地是否已有，都拉 claimed/list 同步权威数据
 *   （lastMessage/preview/redDot/taskMode 等以 list 合并结果为准）；
 *   本地已存在时先乐观恢复为活跃，避免列表等待接口才更新。
 * - 其它 status：本地无则拉 list，本地有则仅恢复活跃态。
 */
async function handleAnnotationTaskClaimed(e: any): Promise<void> {
  const ctx = e?.task_context ?? e?.payload?.task_context ?? {};
  const task = e?.task ?? e?.payload?.task;
  const taskID: string | undefined = ctx?.taskID ?? task?.taskID;
  const imConversationID: string | undefined = ctx?.imConversationID ?? task?.imConversationID;
  if (!taskID && !imConversationID) return;

  const status: number | undefined = task?.status ?? ctx?.status;

  // 记录 taskSource（暂不落业务逻辑；对照 AnnotationTaskSource / ANNOTATION_TASK_SOURCE_LABEL）
  const taskSourceRaw = task?.taskSource;
  const taskSource =
    typeof taskSourceRaw === 'number' ? taskSourceRaw : undefined;
  const taskSourceLabel =
    taskSource != null && taskSource in ANNOTATION_TASK_SOURCE_LABEL
      ? ANNOTATION_TASK_SOURCE_LABEL[taskSource as keyof typeof ANNOTATION_TASK_SOURCE_LABEL]
      : undefined;
  console.log('[ClaimedStore] annotation_task_claimed', {
    taskID,
    imConversationID,
    status,
    taskSource,
    taskSourceLabel,
    taskMode: task?.taskMode,
    // 例：taskSource===1 → USER_MESSAGE 用户消息触发的普通人工任务
    isUserMessage:
      taskSource === AnnotationTaskSource.USER_MESSAGE,
  });

  await ensureClaimedConversationsHydrated();

  const match = { imConversationID, taskID };

  // status=1：新认领的活跃任务，统一拉 claimed/list 同步权威数据
  if (status === 1) {
    // 本地已有则先乐观恢复为活跃（置灰/被接管 → 活跃），列表即时更新
    const next = applyTaskClaimedToConversations(list, match);
    if (next) {
      list = next;
      commit('annotation_task_claimed');
    }
    console.log('[ClaimedStore] annotation_task_claimed status=1，拉取 claimed/list', {
      taskID,
      imConversationID,
      exists: conversationExists(list, match),
    });
    void syncClaimedList({ match, tag: 'annotation_task_claimed' });
    return;
  }

  // 其它 status：本地无则拉 list；本地有则仅恢复活跃态
  const exists = conversationExists(list, match);
  if (!exists) {
    console.log('[ClaimedStore] annotation_task_claimed 本地未命中，延时轮询 claimed/list', {
      taskID,
      imConversationID,
      delayMs: CLAIMED_SYNC_DELAY_MS,
    });
    void syncClaimedList({ match, tag: 'annotation_task_claimed' });
    return;
  }

  const next = applyTaskClaimedToConversations(list, match);
  if (next) {
    list = next;
    commit('annotation_task_claimed');
  }
}

/**
 * 客服上报（transfer_reported）：仅通知主管「请帮忙接管」，不改变任务归属。
 * - 不拉 claimed/list
 * - 主管侧不改本地会话（勿把历史会话恢复为 active）
 * - 弹窗跳转由根布局处理
 */
async function handleTransferReported(_e: any): Promise<void> {
  if (getRole() === 'supervisor') return;
}

async function handleOwnershipChanged(e: any): Promise<void> {
  const reason: string | undefined = e?.reason ?? e?.payload?.reason;
  const taskID: string | undefined = e?.taskID ?? e?.payload?.taskID;
  const ctx = e?.task_context ?? e?.payload?.task_context ?? {};
  const imConversationID: string | undefined = ctx?.imConversationID;
  const previousAssigneeId: string | undefined = e?.previousAssigneeId ?? e?.payload?.previousAssigneeId;
  const currentAssigneeId: string | undefined = e?.currentAssigneeId ?? e?.payload?.currentAssigneeId;
  const me = getAgentId();
  const involved =
    (!!previousAssigneeId && previousAssigneeId === me) ||
    (!!currentAssigneeId && currentAssigneeId === me);
  if (!taskID && !imConversationID) return;

  // 客服：主管归还会话。
  // 注意：这里「不」立即清本地置灰标记（否则会话会先本地转活跃，
  //   触发聊天页在 claimed/list 命中前提前刷新）。
  //   统一交给下方 syncClaimedList(present) —— claimed/list 命中并写缓存后，
  //   merge 会把该会话 inactive/supervisorTakeover 清零转活跃，
  //   聊天页据「置灰→活跃」的缓存变更再刷新接口与历史消息。
  if (reason === 'return_to_agent' || reason === 'return_to_agent_original_offline') {
    if (currentAssigneeId === me) {
      await ensureClaimedConversationsHydrated();
      console.log('[ClaimedStore] 收到归还客服 ownership_changed，等待 claimed/list 命中后再转活跃', {
        taskID,
        imConversationID,
        previousAssigneeId,
        currentAssigneeId,
      });
    }
  } else if (reason === 'supervisor_takeover') {
    // 仅处理“从我这里被接管”的会话：本地置灰 + 弹窗。
    // 接手方（currentAssigneeId === me）绝不置灰，防 previousAssigneeId 缺失时误伤自己
    if (currentAssigneeId !== me && (!previousAssigneeId || previousAssigneeId === me)) {
      await ensureClaimedConversationsHydrated();

      console.log('[ClaimedStore] 收到主管接管 ownership_changed，标记 supervisorTakeover', {
        taskID,
        imConversationID,
        previousAssigneeId,
        currentAssigneeId,
      });

      const local = list.find(
        (c) => (imConversationID && c.imConversationID === imConversationID) || c.id === taskID,
      );
      const actorName = local?.from || ctx?.actorPlatformNickname?.trim() || ctx?.actorPlatformID || '教练';
      const audienceName = local?.to || ctx?.audiencePlatformNickname?.trim() || ctx?.audiencePlatformID || '学员';

      const next = applySupervisorTakeoverToConversations(list, { taskID, imConversationID });
      if (next !== list) {
        list = next;
        commit('ownership_supervisor_takeover');
      } else if (scope) {
        // 会话尚未在内存/缓存中：直接对缓存做增量标记，待其出现时保持置灰
        scheduleMutateClaimedConversationsCache(
          scope,
          (cached) => {
            const patched = applySupervisorTakeoverToConversations(cached, { taskID, imConversationID });
            return patched !== cached ? patched : null;
          },
          'ownership_supervisor_takeover',
        );
      }

      const now = Date.now();
      if (now - lastTakeoverAlertAt >= TAKEOVER_ALERT_THROTTLE_MS) {
        lastTakeoverAlertAt = now;
        emitTakeover({ taskID, imConversationID, actorName, audienceName });
      }
    }
  }

  // 与我相关：统一延时轮询 claimed/list 直至数据正确。
  // 方向只看归属结果，不看 reason：同一个 reason 下接手方等 present、交出方等 absent。
  // 例如主管归还时也会收到 return_to_agent，但它是交出方，应等会话从自己列表消失。
  if (!involved) return;
  if (
    reason !== 'supervisor_takeover' &&
    reason !== 'return_to_agent' &&
    reason !== 'return_to_agent_original_offline' &&
    reason !== 'manual_transfer'
  ) {
    return;
  }
  const match = await resolveConversationMatch({ taskID, imConversationID });
  const expect: SyncClaimedExpect = currentAssigneeId === me ? 'present' : 'absent';
  void syncClaimedList({
    match,
    expect,
    tag: `ownership_changed.${reason}`,
  });
}

/**
 * 主管接管成功：将接手任务 upsert 进列表内存 + 写盘（含 fromAgent*）。
 * 聊天页应调用本 API，禁止直写 AsyncStorage。
 */
export async function upsertSupervisorTakeoverConversation(
  conv: MockConversation,
): Promise<void> {
  await ensureClaimedConversationsHydrated();
  console.log('[ClaimedStore] upsert 主管接管会话', {
    taskID: conv.id,
    imConversationID: conv.imConversationID,
    fromAgentId: conv.fromAgentId,
  });
  list = upsertConversation(list, conv);
  commit('supervisor_takeover');
}

/**
 * 主管：接管成功 → 统一延时轮询 claimed/list（0.5s × 最多 5 次，命中 imConversationID 为止）。
 * 聊天页会先 upsert 本地会话（含 fromAgent*）；过早拉 list 会把它 merge 成 inactive，
 * 因此开启 grace 宽限期保护，超时弹「接管超时」。
 */
/**
 * 主管：接管成功 → 统一延时轮询 claimed/list（0.5s × 最多 5 次）。
 * 聊天页会先 upsert 本地会话（含 fromAgent*）；过早拉 list 会把它 merge 成 inactive，
 * 因此开启 grace 宽限期保护，超时弹「接管超时」。
 *
 * 注意：服务端 task_context 常缺 imConversationID（仅有 taskID/threadID），
 * 此时回退用 taskID 轮询（claimed/list 按 taskID 命中即可）。
 */
async function handleSupervisorTakeoverResult(e: any): Promise<void> {
  const ok = e?.ok ?? e?.payload?.ok;
  if (!ok) return;

  const ctx = e?.task_context ?? e?.payload?.task_context ?? {};
  const { taskID, imConversationID } = await resolveConversationMatch({
    taskID: e?.taskID ?? e?.payload?.taskID,
    imConversationID: ctx?.imConversationID,
  });

  if (!taskID && !imConversationID) {
    console.warn('[ClaimedStore] 主管接管成功但缺少 taskID/imConversationID，无法轮询 claimed/list');
    appAlert('接管超时', '缺少任务标识，无法同步会话列表，请下拉刷新后重试');
    return;
  }

  console.log('[ClaimedStore] 主管接管成功，计划延时轮询 claimed/list', {
    taskID,
    imConversationID,
    currentAssigneeId: e?.currentAssigneeId ?? e?.payload?.currentAssigneeId,
    delayMs: CLAIMED_SYNC_DELAY_MS,
    maxAttempts: CLAIMED_SYNC_MAX_ATTEMPTS,
    matchBy: imConversationID ? 'imConversationID' : 'taskID',
  });
  void syncClaimedList({
    match: { taskID, imConversationID },
    grace: true,
    tag: 'supervisor_takeover_result',
    timeoutAlert: { title: '接管超时', message: '会话列表同步失败，请下拉刷新后重试' },
  });
}

/**
 * 主管：归还成功 → 统一延时轮询 claimed/list 直到该会话不再属于自己，再打 returnedToAgent 标记。
 * 等待同步完成后再写本地标记，避免基于未同步的列表状态写缓存导致标记被后续 merge 冲掉。
 */
async function handleSupervisorReturnToAgentResult(e: any): Promise<void> {
  const ok = e?.ok ?? e?.payload?.ok;
  if (!ok) return;

  const ctx = e?.task_context ?? e?.payload?.task_context ?? {};
  // task_context 常只带 taskID/threadID，需回退反查 imConversationID，
  // 否则与 ownership_changed 的 match 不一致，同步去重会失效
  const match = await resolveConversationMatch({
    taskID: e?.taskID ?? e?.payload?.taskID,
    imConversationID: ctx?.imConversationID,
  });

  console.log('[ClaimedStore] 主管归还客服成功，延时轮询 claimed/list 后标记 returnedToAgent', {
    ...match,
    currentAssigneeId: e?.currentAssigneeId ?? e?.payload?.currentAssigneeId,
  });

  if (!match.taskID && !match.imConversationID) return;

  // 先同步到「list 已不再包含该会话」，再打归还标记，避免 merge 把标记冲掉
  await syncClaimedList({
    match,
    expect: 'absent',
    tag: 'supervisor_return_to_agent_result',
  });

  await ensureClaimedConversationsHydrated();
  const next = applyReturnedToAgentToConversations(list, match);
  if (next !== list) {
    list = next;
    commit('supervisor_return_to_agent');
  } else if (scope) {
    scheduleReturnedToAgentCache(scope, match);
  }
}

/** 客服「已处理」成功（ack_pending_result ok）→ 清除会话红点 */
async function handleAckPendingResult(e: any): Promise<void> {
  const ok = e?.ok ?? e?.payload?.ok;
  if (!ok) return;

  const taskID: string | undefined = e?.taskID ?? e?.payload?.taskID;
  const ctx = e?.task_context ?? e?.payload?.task_context ?? {};
  const imConversationID: string | undefined = ctx?.imConversationID;
  if (!taskID && !imConversationID) return;

  await ensureClaimedConversationsHydrated();
  const next = clearConversationRedDot(list, { taskID, imConversationID });
  if (next) {
    list = next;
    commit('ack_pending_result');
  } else if (scope) {
    scheduleMutateClaimedConversationsCache(
      scope,
      (cached) => clearConversationRedDot(cached, { taskID, imConversationID }),
      'ack_pending_result',
    );
  }
}

/** 客服：切换 AI/人工模式成功 → 更新会话列表 taskMode 并写缓存 */
async function handleSetTaskModeResult(e: any): Promise<void> {
  const ok = e?.ok ?? e?.payload?.ok;
  if (!ok) return;

  const taskMode = (e?.taskMode ?? e?.payload?.taskMode) as TaskMode | undefined;
  if (taskMode !== 'human' && taskMode !== 'ai_assisted') return;

  const taskID: string | undefined = e?.taskID ?? e?.payload?.taskID;
  const ctx = e?.task_context ?? e?.payload?.task_context ?? {};
  const imConversationID: string | undefined = ctx?.imConversationID;
  if (!taskID && !imConversationID) return;

  await ensureClaimedConversationsHydrated();
  console.log('[ClaimedStore] set_task_mode_result，更新 taskMode', {
    taskID,
    imConversationID,
    taskMode,
  });

  const next = applyTaskModeToConversations(list, { taskID, imConversationID, taskMode });
  if (next) {
    list = next;
    commit('set_task_mode_result');
  } else if (scope) {
    scheduleMutateClaimedConversationsCache(
      scope,
      (cached) => applyTaskModeToConversations(cached, { taskID, imConversationID, taskMode }),
      'set_task_mode_result',
    );
  }
}

/**
 * 标记任务完成成功：按 imConversationID（兜底 taskID）置灰本地会话列表。
 */
async function handleCompleteTaskResult(e: any): Promise<void> {
  const ok = e?.ok ?? e?.payload?.ok;
  if (!ok) return;

  const taskID: string | undefined = e?.taskID ?? e?.payload?.taskID;
  const ctx = e?.task_context ?? e?.payload?.task_context ?? {};
  const imConversationID: string | undefined = ctx?.imConversationID;
  if (!taskID && !imConversationID) return;

  await ensureClaimedConversationsHydrated();
  console.log('[ClaimedStore] complete_task_result，会话置灰', {
    taskID,
    imConversationID,
  });

  const next = applyInactiveToConversations(list, { taskID, imConversationID });
  if (next) {
    list = next;
    commit('complete_task_result');
  } else if (scope) {
    scheduleMutateClaimedConversationsCache(
      scope,
      (cached) => applyInactiveToConversations(cached, { taskID, imConversationID }),
      'complete_task_result',
    );
  }
}

/**
 * 客服转派成功：发起人侧立刻置灰，并轮询 claimed/list 直至该会话从己方列表消失。
 */
async function handleTransferTaskResult(e: any): Promise<void> {
  const ok = e?.ok ?? e?.payload?.ok;
  if (!ok) return;

  const taskID: string | undefined = e?.taskID ?? e?.payload?.taskID;
  const ctx = e?.task_context ?? e?.payload?.task_context ?? {};
  const imConversationID: string | undefined = ctx?.imConversationID;
  if (!taskID && !imConversationID) return;

  await ensureClaimedConversationsHydrated();
  console.log('[ClaimedStore] transfer_task_result，会话置灰', {
    taskID,
    imConversationID,
    currentAssigneeId: e?.currentAssigneeId ?? e?.payload?.currentAssigneeId,
  });

  const next = applyInactiveToConversations(list, { taskID, imConversationID });
  if (next) {
    list = next;
    commit('transfer_task_result');
  } else if (scope) {
    scheduleMutateClaimedConversationsCache(
      scope,
      (cached) => applyInactiveToConversations(cached, { taskID, imConversationID }),
      'transfer_task_result',
    );
  }

  const match = await resolveConversationMatch({ taskID, imConversationID });
  void syncClaimedList({
    match,
    expect: 'absent',
    tag: 'transfer_task_result',
  });
}

/** 批量转派汇总：补处理成功项，并提示部分失败或整批前置校验失败 */
async function handleTransferTaskBatchResult(e: any): Promise<void> {
  const p = e?.payload ?? e;
  const ok = p?.ok ?? false;
  const error = typeof p?.error === 'string' ? p.error : undefined;
  const succeeded: string[] = Array.isArray(p?.succeededTaskIDs)
    ? p.succeededTaskIDs.map((id: unknown) => String(id).trim()).filter(Boolean)
    : [];
  const failed: string[] = Array.isArray(p?.failedTaskIDs)
    ? p.failedTaskIDs.map((id: unknown) => String(id).trim()).filter(Boolean)
    : [];

  for (const taskID of succeeded) {
    await handleTransferTaskResult({ ok: true, taskID });
  }

  if (error === 'target_agent_off_duty') {
    appAlert('转移失败', formatTransferErrorCode(error));
    return;
  }

  if (!ok && succeeded.length === 0 && failed.length === 0 && error) {
    appAlert('转移失败', formatTransferErrorCode(error));
    return;
  }

  if (failed.length > 0) {
    appAlert(
      '部分转移失败',
      `成功 ${succeeded.length} 个，失败 ${failed.length} 个。失败项请稍后重试。`,
    );
  }
}

/**
 * 从 tasks/detail 等接口回写会话 taskMode / skillGroup 到本地列表缓存。
 * 仅本人会话应调用（主管旁观勿调）。
 */
export function updateConversationTaskMode(params: {
  taskID?: string;
  imConversationID?: string;
  taskMode: TaskMode;
  /** task.skillGroup；缺省时保留缓存中原值 */
  skillGroup?: string;
}): void {
  const { taskMode, skillGroup } = params;
  if (taskMode !== 'human' && taskMode !== 'ai_assisted') return;
  if (!params.taskID && !params.imConversationID) return;

  void (async () => {
    await ensureClaimedConversationsHydrated();
    const next = applyTaskModeToConversations(list, {
      taskID: params.taskID,
      imConversationID: params.imConversationID,
      taskMode,
      skillGroup,
    });
    if (next) {
      list = next;
      commit('tasks_detail_task_mode');
    } else if (scope) {
      scheduleMutateClaimedConversationsCache(
        scope,
        (cached) =>
          applyTaskModeToConversations(cached, {
            taskID: params.taskID,
            imConversationID: params.imConversationID,
            taskMode,
            skillGroup,
          }),
        'tasks_detail_task_mode',
      );
    }
  })();
}

/** 找会话缓存实体：主键优先 imConversationID，兜底 taskID */
function findConversationByMatch(match: {
  taskID?: string;
  imConversationID?: string;
}): MockConversation | undefined {
  const imConversationID = match.imConversationID?.trim();
  const taskID = match.taskID?.trim();
  if (!imConversationID && !taskID) return undefined;
  return list.find(
    (c) =>
      (imConversationID && c.imConversationID === imConversationID) ||
      (taskID && c.id === taskID),
  );
}

/**
 * 记录该会话已复审过的 adoptionID，并清除缓存中的 adoptionContext。
 * claimed/list 刷新时 merge：已 handled 的 adoption 不会再写回。
 */
export async function markConversationAdoptionHandled(params: {
  taskID?: string;
  imConversationID?: string;
  adoptionID?: string;
}): Promise<void> {
  if (!params.adoptionID?.trim()) return;
  if (!params.taskID && !params.imConversationID) return;

  await ensureClaimedConversationsHydrated();
  const next = applyHandledAdoptionIDToConversations(list, params);
  if (next) {
    list = next;
    commit('adoption_handled');
  } else if (scope) {
    scheduleMutateClaimedConversationsCache(
      scope,
      (cached) => applyHandledAdoptionIDToConversations(cached, params),
      'adoption_handled',
    );
  }
}

/**
 * 写入 / 补写会话缓存中的待复审 adoptionContext（进房 detail 兜底等）。
 * 已 handled 的 adoptionID 不会写入。
 */
export async function setConversationAdoptionContext(params: {
  taskID?: string;
  imConversationID?: string;
  adoptionContext?: AdoptionContext | null;
}): Promise<void> {
  if (!params.taskID && !params.imConversationID) return;
  if (!pickValidAdoptionContext(params.adoptionContext)) return;

  await ensureClaimedConversationsHydrated();
  const next = applyAdoptionContextToConversations(list, params);
  if (next) {
    list = next;
    commit('adoption_context_set');
  } else if (scope) {
    scheduleMutateClaimedConversationsCache(
      scope,
      (cached) => applyAdoptionContextToConversations(cached, params),
      'adoption_context_set',
    );
  }
}

/** 该 adoptionID 是否已在本地复审过（读会话列表缓存里的水位） */
export function isConversationAdoptionHandled(params: {
  taskID?: string;
  imConversationID?: string;
  adoptionID?: string;
}): boolean {
  const adoptionID = params.adoptionID?.trim();
  if (!adoptionID) return false;
  return findConversationByMatch(params)?.handledAdoptionID === adoptionID;
}

/**
 * 有候选、且该 adoptionID 未在本会话复审过 → 需要展示复审横幅；否则返回 null。
 * 调用前应确保缓存已 hydrate（进房流程已 await）。
 */
export function pickPendingAdoptionContext(
  adoption: AdoptionContext | null | undefined,
  match: { taskID?: string; imConversationID?: string },
): AdoptionContext | null {
  const valid = pickValidAdoptionContext(adoption);
  if (!valid) return null;
  return isConversationAdoptionHandled({ ...match, adoptionID: valid.adoptionID })
    ? null
    : valid;
}

/** 从会话列表缓存读取待复审 adoptionContext（优先于 tasks/detail） */
export function getCachedPendingAdoptionContext(match: {
  taskID?: string;
  imConversationID?: string;
}): AdoptionContext | null {
  const conv = findConversationByMatch(match);
  return pickPendingAdoptionContext(conv?.adoptionContext, match);
}

/** 清除会话 proactiveActionHints（用户关闭主动触达提醒后） */
export function clearConversationProactiveActionHints(params: {
  taskID?: string;
  imConversationID?: string;
}): void {
  if (!params.taskID && !params.imConversationID) return;

  void (async () => {
    await ensureClaimedConversationsHydrated();
    const next = clearProactiveActionHintsFromConversations(list, params);
    if (next) {
      list = next;
      commit('proactive_action_hints_cleared');
    } else if (scope) {
      scheduleMutateClaimedConversationsCache(
        scope,
        (cached) => clearProactiveActionHintsFromConversations(cached, params),
        'proactive_action_hints_cleared',
      );
    }
  })();
}

/** 更新会话 proactiveActionHints（快捷发送后移除已发送项等） */
export function updateConversationProactiveActionHints(params: {
  taskID?: string;
  imConversationID?: string;
  hints: ProactiveActionHint[];
}): void {
  if (!params.taskID && !params.imConversationID) return;

  void (async () => {
    await ensureClaimedConversationsHydrated();
    const next = setProactiveActionHintsOnConversation(list, params);
    if (next) {
      list = next;
      commit('proactive_action_hints_updated');
    } else if (scope) {
      scheduleMutateClaimedConversationsCache(
        scope,
        (cached) => setProactiveActionHintsOnConversation(cached, params),
        'proactive_action_hints_updated',
      );
    }
  })();
}

/**
 * 初始化全局会话同步：注册 WS/总线监听。
 * 幂等：重复调用只注册一次。返回清理函数（根布局通常不需要调用）。
 */
export function initClaimedConversationsSync(): () => void {
  if (started) return disposeClaimedConversationsSync;
  started = true;

  const chat = getChatService();

  const offGateway = chat.onGatewayEvent((evt: IMGatewayEvent) => {
    const e = evt as any;
    const t = e?.type ?? e?.payload?.type;
    switch (t) {
      case 'annotation_event':
        void handleAnnotationEvent(evt as Extract<IMGatewayEvent, { type: 'annotation_event' }>);
        break;
      case 'ai_review_required':
        void handleAiReviewRequired(evt as Extract<IMGatewayEvent, { type: 'ai_review_required' }>);
        break;
      case 'annotation_task_claimed':
        void handleAnnotationTaskClaimed(e);
        break;
      case 'transfer_reported':
        void handleTransferReported(e);
        break;
      case 'supervisor_takeover_result':
        void handleSupervisorTakeoverResult(e);
        break;
      case 'supervisor_return_to_agent_result':
        void handleSupervisorReturnToAgentResult(e);
        break;
      case 'set_task_mode_result':
        void handleSetTaskModeResult(e);
        break;
      case 'complete_task_result':
        void handleCompleteTaskResult(e);
        break;
      case 'transfer_task_result':
        void handleTransferTaskResult(e);
        break;
      case 'transfer_task_batch_result':
        void handleTransferTaskBatchResult(e);
        break;
      case 'ack_pending_result':
        void handleAckPendingResult(e);
        break;
      case 'ownership_changed':
        void handleOwnershipChanged(e);
        break;
      default:
        break;
    }
  });

  const offProcessed = subscribeConversationProcessed((p) => {
    void (async () => {
      await ensureClaimedConversationsHydrated();
      const next = clearConversationRedDot(list, p);
      if (next) {
        list = next;
        commit('conversation_processed');
      }
    })();
  });

  const offLastMessage = subscribeConversationLastMessage((p) => {
    enqueueConversationLastMessage(p);
  });

  // WS 重连：对齐 duty/status；若上下班状态变化（如断线过久被自动下班），再刷 claimed/list
  const offConnState = chat.onStateChange((state) => {
    const prev = lastWsConnectionState;
    lastWsConnectionState = state;
    if (state !== 'connected') return;

    const isReconnect =
      wsEverConnected ||
      prev === 'reconnecting' ||
      prev === 'disconnected' ||
      prev === 'connection_timeout';
    wsEverConnected = true;
    if (!isReconnect) return;
    void syncDutyAndClaimedOnWsReconnect();
  });

  disposeFns = [offGateway, offProcessed, offLastMessage, offConnState];
  return disposeClaimedConversationsSync;
}

/** 释放全局会话同步（一般仅测试/登出场景使用） */
export function disposeClaimedConversationsSync(): void {
  cancelAllSyncClaimedList();
  conversationChangeListeners.clear();
  for (const off of disposeFns) {
    try {
      off();
    } catch {
      // ignore
    }
  }
  disposeFns = [];
  started = false;
  wsEverConnected = false;
  lastWsConnectionState = null;
  dutyAfterReconnectInFlight = null;
  lastMessageQueue = [];
  lastMessageFlushing = false;
}
