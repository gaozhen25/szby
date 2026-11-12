// ============================================================
// claimed/list 会话列表本地缓存（按 tenant + role + agent_id 隔离）
// - 底层存储：Native = expo-sqlite，Web = Dexie/IndexedDB（见 @/core/db）
// - 模块级防抖：多组件/重复事件合并为一次写盘
// - 行级写入：与上一次落库快照 diff，只写变更行，避免整表 JSON 重写
// - 首次读取时自动迁移旧版 AsyncStorage 整包缓存，迁移后删除旧 key
// ============================================================
import AsyncStorage from '@react-native-async-storage/async-storage';
import type { MockConversation } from '@/mock/data';
import {
  getConversationSortTime,
  preserveEphemeralLocalFields,
} from '@/lib/claimed-conversations-merge';
import { conversationRepo, type ConversationRow } from '@/core/db';

export type ClaimedConversationsScope = {
  tenantId: string;
  role: 'agent' | 'supervisor';
  agentId: string;
};

/** 旧版 AsyncStorage 整包缓存格式（仅用于一次性迁移） */
export type ClaimedConversationsCacheV1 = {
  version: 1;
  scope: ClaimedConversationsScope;
  updatedAt: number;
  conversations: MockConversation[];
};

/** 旧版 AsyncStorage key 前缀，仅迁移与清理时使用 */
const LEGACY_KEY_PREFIX = 'claimed_conversations_v1:';
const FLUSH_DEBOUNCE_MS = 400;
const ANNOTATION_EVENT_DEDUP_TTL_MS = 60_000;

type CacheMutator = (list: MockConversation[]) => MockConversation[] | null;

type PendingCacheWork = {
  replace?: MockConversation[];
  mutators: CacheMutator[];
  reason: string;
};

const pendingWork = new Map<string, PendingCacheWork>();
const flushTimers = new Map<string, ReturnType<typeof setTimeout>>();
/** 同一 key 串行写盘，避免旧的 await save 覆盖更新的 pending */
const flushChains = new Map<string, Promise<void>>();
const seenAnnotationEventIds = new Map<string, number>();

/** 上一次成功落库的内容：行主键 → { 序列化结果, 实体 }，用于 diff 出变更行 */
type SnapshotEntry = { json: string; conv: MockConversation };
type ScopeSnapshot = Map<string, SnapshotEntry>;
const persistedSnapshots = new Map<string, ScopeSnapshot>();
const loadInFlight = new Map<string, Promise<MockConversation[]>>();

/** 这些 reason 允许主动丢掉 ephemeral（黄点），replace 时不再从 pending 回填 */
const DROP_EPHEMERAL_CACHE_REASONS = new Set([
  'proactive_action_hints_cleared',
  'annotation_event_task_removed',
  'complete_task_result',
]);

/** 隔离键：既是内存 Map 的 key，也是 DB 行的 scope_key */
function storageKey(scope: ClaimedConversationsScope): string {
  return `${scope.tenantId}:${scope.role}:${scope.agentId}`;
}

function legacyStorageKey(scope: ClaimedConversationsScope): string {
  return `${LEGACY_KEY_PREFIX}${storageKey(scope)}`;
}

/** 行主键：优先 taskID，缺失时回退 IM 会话 id */
function conversationRowKey(conv: MockConversation): string {
  const taskID = conv.id?.trim();
  if (taskID) return taskID;
  const imConversationID = conv.imConversationID?.trim();
  return imConversationID ? `im:${imConversationID}` : '';
}

/** 与列表排序口径一致（含秒/毫秒归一），无有效时间记 0 */
function conversationSortTime(conv: MockConversation): number {
  return getConversationSortTime(conv) ?? 0;
}

function snapshotToList(snapshot: ScopeSnapshot): MockConversation[] {
  return Array.from(snapshot.values(), (entry) => entry.conv);
}

function rowsToSnapshot(rows: ConversationRow[]): ScopeSnapshot {
  const snapshot: ScopeSnapshot = new Map();
  for (const row of rows) {
    try {
      snapshot.set(row.taskID, { json: row.data, conv: JSON.parse(row.data) as MockConversation });
    } catch {
      // 单行损坏不影响整表读取
    }
  }
  return snapshot;
}

/** 与上一次落库快照对比，产出待写入行与待删除主键 */
function buildDiff(
  scopeKey: string,
  conversations: MockConversation[],
  previous: ScopeSnapshot,
  updatedAt: number,
): { upserts: ConversationRow[]; deleteTaskIDs: string[]; snapshot: ScopeSnapshot } {
  const snapshot: ScopeSnapshot = new Map();
  const upserts: ConversationRow[] = [];
  let skipped = 0;

  for (const conv of conversations) {
    const rowKey = conversationRowKey(conv);
    if (!rowKey) {
      skipped += 1;
      continue;
    }
    if (snapshot.has(rowKey)) continue;
    const json = JSON.stringify(conv);
    snapshot.set(rowKey, { json, conv });
    if (previous.get(rowKey)?.json === json) continue;
    upserts.push({
      scopeKey,
      taskID: rowKey,
      imConversationID: conv.imConversationID?.trim() ?? '',
      sortTime: conversationSortTime(conv),
      inactive: conv.inactive ? 1 : 0,
      updatedAt,
      data: json,
    });
  }

  const deleteTaskIDs: string[] = [];
  for (const rowKey of previous.keys()) {
    if (!snapshot.has(rowKey)) deleteTaskIDs.push(rowKey);
  }

  if (skipped) {
    console.warn('[ClaimedCache] 会话缺少 taskID/imConversationID，无法落库', {
      scopeKey,
      skipped,
    });
  }

  return { upserts, deleteTaskIDs, snapshot };
}

function getOrCreatePending(key: string, reason: string): PendingCacheWork {
  let pending = pendingWork.get(key);
  if (!pending) {
    pending = { mutators: [], reason };
    pendingWork.set(key, pending);
  }
  pending.reason = reason;
  return pending;
}

function scheduleFlush(scope: ClaimedConversationsScope): void {
  const key = storageKey(scope);
  if (flushTimers.has(key)) return;
  flushTimers.set(key, setTimeout(() => {
    flushTimers.delete(key);
    const prev = flushChains.get(key) ?? Promise.resolve();
    const next = prev
      .catch(() => undefined)
      .then(() => flushPending(scope, key));
    flushChains.set(key, next);
  }, FLUSH_DEBOUNCE_MS));
}

async function flushPending(scope: ClaimedConversationsScope, key: string): Promise<void> {
  const pending = pendingWork.get(key);
  pendingWork.delete(key);
  if (!pending) return;

  if (pending.replace) {
    await saveClaimedConversationsCache(scope, pending.replace, pending.reason);
    return;
  }

  if (!pending.mutators.length) return;

  // 已 hydrate 时直接命中内存快照，不产生额外 I/O
  let list = await loadClaimedConversationsCache(scope);
  let changed = false;
  for (const mutator of pending.mutators) {
    const next = mutator(list);
    if (next && next !== list) {
      list = next;
      changed = true;
    }
  }
  if (changed) {
    await saveClaimedConversationsCache(scope, list, pending.reason);
  }
}

/** annotation_event 去重：同一 eventID 只写盘一次 */
export function consumeAnnotationEventForCache(eventID?: string): boolean {
  if (!eventID) return false;
  const now = Date.now();
  for (const [id, ts] of seenAnnotationEventIds) {
    if (now - ts > ANNOTATION_EVENT_DEDUP_TTL_MS) seenAnnotationEventIds.delete(id);
  }
  if (seenAnnotationEventIds.has(eventID)) return true;
  seenAnnotationEventIds.set(eventID, now);
  return false;
}

/** 全量替换缓存（claimed/list 合并等） */
export function scheduleReplaceClaimedConversationsCache(
  scope: ClaimedConversationsScope,
  conversations: MockConversation[],
  reason = 'replace',
): void {
  const key = storageKey(scope);
  const pending = getOrCreatePending(key, reason);

  let next = conversations;

  // 防抖窗口内先有 mutator（如 eventType=5 只写盘）再被 replace：把 mutator 打到新全量上，禁止直接丢弃
  if (pending.mutators.length) {
    for (const mutator of pending.mutators) {
      const patched = mutator(next);
      if (patched) next = patched;
    }
  }

  // 防抖窗口内连续 replace：非主动清除时，保留上一版里的黄点/复审，避免 claimed/list 竞态抹掉
  if (pending.replace && !DROP_EPHEMERAL_CACHE_REASONS.has(reason)) {
    const merged = preserveEphemeralLocalFields(pending.replace, next);
    if (merged !== next) {
      console.log('[ClaimedCache] replace 合并保留 ephemeral 字段', {
        reason,
        prevReason: pending.reason,
      });
      next = merged;
    }
  }

  pending.replace = next;
  pending.mutators = [];
  pending.reason = reason;
  scheduleFlush(scope);
}

/** 增量修改缓存：多个 mutator 在同一防抖窗口内合并为一次读-改-写 */
export function scheduleMutateClaimedConversationsCache(
  scope: ClaimedConversationsScope,
  mutator: CacheMutator,
  reason = 'mutate',
): void {
  const key = storageKey(scope);
  const pending = getOrCreatePending(key, reason);
  // 若已有全量 replace：直接打在 replace 结果上，避免接管标记等增量被丢弃
  if (pending.replace) {
    const next = mutator(pending.replace);
    if (next) pending.replace = next;
    pending.reason = reason;
    scheduleFlush(scope);
    return;
  }
  pending.mutators.push(mutator);
  scheduleFlush(scope);
}

/**
 * 早期版本把带 claimed_conversations_v1: 前缀的字符串直接当作 scope_key 写过库，
 * 且写完就删掉了 AsyncStorage 原始数据。这里把那批行搬到现在的 scope_key 下，
 * 否则它们会永远查不到。待存量设备都升级过后可移除。
 */
async function adoptLegacyScopeRows(
  scope: ClaimedConversationsScope,
  scopeKey: string,
  currentRows: ConversationRow[],
): Promise<ConversationRow[] | null> {
  const legacyScopeKey = legacyStorageKey(scope);
  const legacyRows = await conversationRepo.loadScope(legacyScopeKey);
  if (!legacyRows.length) return null;

  // 同一 taskID 以当前键的版本为准；旧键的价值在于补回 claimed/list 不返回的历史（置灰）会话
  const byTaskID = new Map<string, ConversationRow>();
  for (const row of legacyRows) byTaskID.set(row.taskID, { ...row, scopeKey });
  for (const row of currentRows) byTaskID.set(row.taskID, row);
  const mergedRows = Array.from(byTaskID.values()).sort((a, b) => b.sortTime - a.sortTime);

  const conversations = snapshotToList(rowsToSnapshot(mergedRows));
  const { upserts } = buildDiff(scopeKey, conversations, new Map(), Date.now());
  await conversationRepo.applyDiff(scopeKey, { upserts, deleteTaskIDs: [] });
  // 搬运成功后才清旧键，中途失败下次启动可重试
  await conversationRepo.clearScope(legacyScopeKey);

  console.log('[ClaimedCache] 已将早期 scope_key 下的会话并回新键', {
    scope,
    from: legacyScopeKey,
    to: scopeKey,
    recovered: legacyRows.length,
    total: mergedRows.length,
  });
  return mergedRows;
}

/**
 * 旧版整包缓存 → 本地数据库的一次性迁移。
 * 必须写库成功后才删旧 key，中途失败下次启动可重试。
 */
async function migrateLegacyCache(
  scope: ClaimedConversationsScope,
  scopeKey: string,
): Promise<MockConversation[] | null> {
  const legacyKey = legacyStorageKey(scope);
  let raw: string | null = null;
  try {
    raw = await AsyncStorage.getItem(legacyKey);
  } catch (e) {
    console.warn('[ClaimedCache] 读取旧版 AsyncStorage 缓存失败', { legacyKey, error: e });
    return null;
  }
  if (!raw) return null;

  let conversations: MockConversation[] = [];
  try {
    const parsed = JSON.parse(raw) as Partial<ClaimedConversationsCacheV1> | null;
    if (parsed?.version === 1 && Array.isArray(parsed.conversations)) {
      conversations = parsed.conversations as MockConversation[];
    } else {
      console.log('[ClaimedCache] 旧版缓存版本不匹配，直接丢弃', {
        legacyKey,
        version: parsed?.version,
      });
    }
  } catch (e) {
    console.warn('[ClaimedCache] 旧版缓存解析失败，直接丢弃', { legacyKey, error: e });
  }

  if (conversations.length) {
    const { upserts, snapshot } = buildDiff(scopeKey, conversations, new Map(), Date.now());
    await conversationRepo.applyDiff(scopeKey, { upserts, deleteTaskIDs: [] });
    persistedSnapshots.set(scopeKey, snapshot);
  } else {
    persistedSnapshots.set(scopeKey, new Map());
  }

  await AsyncStorage.removeItem(legacyKey).catch(() => undefined);
  console.log('[ClaimedCache] 旧版 AsyncStorage 缓存已迁移至本地数据库', {
    scope,
    legacyKey,
    count: conversations.length,
  });
  return conversations;
}

function summarizeClaimedCacheList(list: MockConversation[]) {
  let active = 0;
  let inactive = 0;
  for (const c of list) {
    if (c.inactive) inactive += 1;
    else active += 1;
  }
  return {
    count: list.length,
    active,
    inactive,
    sample: list.slice(0, 5).map((c) => ({
      id: c.id,
      imConversationID: c.imConversationID,
      inactive: !!c.inactive,
      from: c.from,
      to: c.to,
    })),
  };
}

export async function loadClaimedConversationsCache(
  scope: ClaimedConversationsScope,
): Promise<MockConversation[]> {
  const key = storageKey(scope);
  const cached = persistedSnapshots.get(key);
  if (cached) {
    const conversations = snapshotToList(cached);
    console.log('[ClaimedCache] 读取本地缓存', {
      source: 'memory',
      scope,
      scopeKey: key,
      ...summarizeClaimedCacheList(conversations),
    });
    return conversations;
  }

  const existing = loadInFlight.get(key);
  if (existing) {
    console.log('[ClaimedCache] 读取本地缓存：等待进行中的读盘', { scope, scopeKey: key });
    return existing;
  }

  const task = (async (): Promise<MockConversation[]> => {
    const startedAt = Date.now();
    console.log('[ClaimedCache] 开始读取本地缓存', { source: 'disk', scope, scopeKey: key });
    try {
      let rows = await conversationRepo.loadScope(key);
      // 无条件检查旧 scope_key：新键即便已有 claimed/list 拉回的活跃会话，
      // 历史（置灰）会话也只存在于本地，不并回来就永久丢失
      const adopted = await adoptLegacyScopeRows(scope, key, rows);
      if (adopted) rows = adopted;

      if (rows.length) {
        const snapshot = rowsToSnapshot(rows);
        persistedSnapshots.set(key, snapshot);
        const conversations = snapshotToList(snapshot);
        console.log('[ClaimedCache] 读取本地缓存完成', {
          source: 'disk',
          scope,
          scopeKey: key,
          elapsedMs: Date.now() - startedAt,
          rowCount: rows.length,
          ...summarizeClaimedCacheList(conversations),
        });
        return conversations;
      }

      const migrated = await migrateLegacyCache(scope, key);
      if (migrated) {
        console.log('[ClaimedCache] 读取本地缓存完成（旧版迁移）', {
          source: 'legacy_migrate',
          scope,
          scopeKey: key,
          elapsedMs: Date.now() - startedAt,
          ...summarizeClaimedCacheList(migrated),
        });
        return migrated;
      }

      persistedSnapshots.set(key, new Map());
      console.log('[ClaimedCache] 读取本地缓存完成：无数据', {
        source: 'disk',
        scope,
        scopeKey: key,
        elapsedMs: Date.now() - startedAt,
        count: 0,
        active: 0,
        inactive: 0,
      });
      return [];
    } catch (e) {
      // 不写入快照（区别于「读到空表」），后续写盘会跳过，避免用空快照覆盖盘上数据。
      // Native 上最常见的原因是 expo-sqlite 原生模块缺失，需要重新构建原生包。
      console.warn('[ClaimedCache] 读取本地缓存失败，本次不落盘等待重试', {
        scope,
        scopeKey: key,
        elapsedMs: Date.now() - startedAt,
        error: e,
      });
      return [];
    } finally {
      loadInFlight.delete(key);
    }
  })();

  loadInFlight.set(key, task);
  return task;
}

export async function saveClaimedConversationsCache(
  scope: ClaimedConversationsScope,
  conversations: MockConversation[],
  reason = 'unknown',
): Promise<void> {
  const key = storageKey(scope);
  try {
    // 需要知道盘上现状才能算出删除项，未 hydrate 时先读一次
    if (!persistedSnapshots.has(key)) await loadClaimedConversationsCache(scope);
    const previous = persistedSnapshots.get(key);
    // 读库失败时快照为空（区别于「读到空表」），此时若按空快照写入会漏掉删除项，
    // 让已结束的会话在下次冷启动复活，因此直接放弃本次写盘等待重试
    if (!previous) {
      console.warn('[ClaimedCache] 落库快照不可用（读库失败），跳过本次写盘', { reason, scopeKey: key });
      return;
    }

    const updatedAt = Date.now();
    const { upserts, deleteTaskIDs, snapshot } = buildDiff(key, conversations, previous, updatedAt);

    if (!upserts.length && !deleteTaskIDs.length) {
      persistedSnapshots.set(key, snapshot);
      return;
    }

    await conversationRepo.applyDiff(key, { upserts, deleteTaskIDs });
    persistedSnapshots.set(key, snapshot);
    console.log('[ClaimedCache] 更新本地缓存', {
      reason,
      scope,
      scopeKey: key,
      updatedAt,
      count: conversations.length,
      upserts: upserts.length,
      deletes: deleteTaskIDs.length,
    });
  } catch (e) {
    console.warn('[ClaimedCache] 更新本地缓存失败', { reason, scope, scopeKey: key, error: e });
  }
}

export async function clearClaimedConversationsCache(
  scope: ClaimedConversationsScope,
  reason = 'unknown',
): Promise<void> {
  const key = storageKey(scope);
  pendingWork.delete(key);
  const timer = flushTimers.get(key);
  if (timer) {
    clearTimeout(timer);
    flushTimers.delete(key);
  }
  try {
    await conversationRepo.clearScope(key);
    persistedSnapshots.set(key, new Map());
    await AsyncStorage.removeItem(legacyStorageKey(scope)).catch(() => undefined);
    console.log('[ClaimedCache] 清空本地缓存', { reason, scope, scopeKey: key });
  } catch (e) {
    console.warn('[ClaimedCache] 清空本地缓存失败', { reason, scope, scopeKey: key, error: e });
  }
}
