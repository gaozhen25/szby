// ============================================================
// claimed/list active 会话 → 合并到本地缓存会话库
// - 主键优先 imConversationID，兜底 taskID（id）；匹配时二者任一命中即可（避免双写重复行）
// - 每次 claimed/list：接口字段一律以本次 list 为准整份覆盖（含 taskMode / lastMessage / preview 等）
// - hasRedDot 例外：用末条 + 本地 redDotAckServerMsgID 重算（避免「已处理」后 list 仍对方末条又盖回红点）
// - 仅保留接口不返回的本地扩展（fromAgentId / fromAgentAccount / redDotAckServerMsgID）
// - claimed/list 返回的会话：supervisorTakeover=false、returnedToAgent=false、inactive=false
// - claimed/list 不包含的会话：置灰 inactive=true（保留历史，不改其它字段）
// - active 在上、history 在下；各区内按 lastMessage.sendTime 倒序
// ============================================================
import type { MockConversation } from '@/mock/data';
import type { AdoptionContext } from '@/core/im/types';
import { normalizeSendTimeMs } from '@/core/im/utils';
import {
  resolveConversationHasRedDot,
} from '@/lib/conversation-red-dot';

function pickValidAdoptionContext(
  adoption?: AdoptionContext | null,
): AdoptionContext | undefined {
  if (!adoption || !Array.isArray(adoption.candidates) || adoption.candidates.length === 0) {
    return undefined;
  }
  return adoption;
}

/**
 * claimed/list 合并时的 adoptionContext 策略：
 * - list 有待复审且 adoptionID ≠ 本地 handledAdoptionID → 写入本地
 * - list 有待复审但 adoptionID 已 handled → 一定不更新（保持清除态）
 * - list 无待复审 → 保留本地 WS 写入的 pending（未 handled）
 */
export function resolveAdoptionContextOnClaimedMerge(
  local: Pick<MockConversation, 'adoptionContext' | 'handledAdoptionID'>,
  remote: Pick<MockConversation, 'adoptionContext'>,
): AdoptionContext | undefined {
  const remoteAdoption = pickValidAdoptionContext(remote.adoptionContext);
  if (remoteAdoption) {
    const remoteID = remoteAdoption.adoptionID?.trim();
    if (remoteID && local.handledAdoptionID === remoteID) {
      return undefined;
    }
    return remoteAdoption;
  }
  const localAdoption = pickValidAdoptionContext(local.adoptionContext);
  if (!localAdoption) return undefined;
  const localID = localAdoption.adoptionID?.trim();
  if (localID && local.handledAdoptionID === localID) return undefined;
  return localAdoption;
}

/** commit / 并发刷新时回填 adoptionContext：已 handled 的不回填 */
function resolvePreservedAdoptionContext(
  item: MockConversation,
  src: MockConversation,
): AdoptionContext | undefined {
  const itemAdoption = pickValidAdoptionContext(item.adoptionContext);
  if (itemAdoption) {
    const id = itemAdoption.adoptionID?.trim();
    if (id && item.handledAdoptionID === id) return undefined;
    return itemAdoption;
  }
  const srcAdoption = pickValidAdoptionContext(src.adoptionContext);
  if (!srcAdoption) return undefined;
  const srcID = srcAdoption.adoptionID?.trim();
  // 本次已标记 handled（或 item 已清空）：不要把旧 pending 填回去
  if (srcID && (item.handledAdoptionID === srcID || src.handledAdoptionID === srcID)) {
    return undefined;
  }
  return srcAdoption;
}
/** 是否为映射兜底昵称（admin/context 缺字段时会出现「教练/学员」） */
export function isPlaceholderConversationName(name: string | undefined): boolean {
  const n = (name ?? '').trim();
  return !n || n === '教练' || n === '学员';
}

/** 两行是否指向同一会话（imConversationID 或 taskID 任一相等） */
export function isSameConversationIdentity(
  a: Pick<MockConversation, 'imConversationID' | 'id'>,
  b: Pick<MockConversation, 'imConversationID' | 'id'>,
): boolean {
  const aIm = a.imConversationID?.trim();
  const bIm = b.imConversationID?.trim();
  if (aIm && bIm && aIm === bIm) return true;
  if (a.id && b.id && a.id === b.id) return true;
  return false;
}

/** 在列表中按 imConversationID 或 taskID 查找（兼容缺一端主键） */
export function findConversationIndexByIdentity(
  list: MockConversation[],
  match: Pick<MockConversation, 'imConversationID' | 'id'>,
): number {
  const im = match.imConversationID?.trim();
  if (im) {
    const byIm = list.findIndex((c) => c.imConversationID?.trim() === im);
    if (byIm >= 0) return byIm;
  }
  if (match.id) {
    const byId = list.findIndex((c) => c.id === match.id);
    if (byId >= 0) return byId;
  }
  return -1;
}

/**
 * 主键 → 下标索引。批量查找时必须先建索引再查，
 * 否则 findConversationIndexByIdentity 逐条全表扫会退化成 O(n²)（数百会话时明显卡主线程）。
 */
export type ConversationIdentityIndex = {
  byIm: Map<string, number>;
  byTask: Map<string, number>;
};

export function buildConversationIdentityIndex(
  list: MockConversation[],
): ConversationIdentityIndex {
  const byIm = new Map<string, number>();
  const byTask = new Map<string, number>();
  for (let i = 0; i < list.length; i++) {
    const im = list[i].imConversationID?.trim();
    if (im && !byIm.has(im)) byIm.set(im, i);
    const id = list[i].id;
    if (id && !byTask.has(id)) byTask.set(id, i);
  }
  return { byIm, byTask };
}

/** 与 findConversationIndexByIdentity 同语义（imConversationID 优先，taskID 兜底） */
export function lookupConversationIndex(
  index: ConversationIdentityIndex,
  match: Pick<MockConversation, 'imConversationID' | 'id'>,
): number {
  const im = match.imConversationID?.trim();
  if (im) {
    const byIm = index.byIm.get(im);
    if (byIm !== undefined) return byIm;
  }
  if (match.id) {
    const byId = index.byTask.get(match.id);
    if (byId !== undefined) return byId;
  }
  return -1;
}

function pickPreferredName(preferred: string | undefined, fallback: string | undefined): string {
  if (!isPlaceholderConversationName(preferred)) return preferred!.trim();
  if (!isPlaceholderConversationName(fallback)) return fallback!.trim();
  return (preferred ?? fallback ?? '').trim();
}

/** 合并重复行：保留信息更全的一条（active、真实昵称、fromAgent、imConversationID 优先） */
export function mergeConversationPair(a: MockConversation, b: MockConversation): MockConversation {
  const preferA =
    // 优先可接待
    Number(!a.inactive) - Number(!b.inactive) ||
    // 优先非兜底昵称
    Number(!isPlaceholderConversationName(a.from) && !isPlaceholderConversationName(a.to)) -
      Number(!isPlaceholderConversationName(b.from) && !isPlaceholderConversationName(b.to)) ||
    // 优先已有 imConversationID
    Number(!!a.imConversationID?.trim()) - Number(!!b.imConversationID?.trim()) ||
    // 优先带接管来源
    Number(!!a.fromAgentId) - Number(!!b.fromAgentId);

  const primary = preferA >= 0 ? a : b;
  const secondary = preferA >= 0 ? b : a;

  return {
    ...secondary,
    ...primary,
    // 主键不可被缺字段的一侧冲掉（接管 upsert 可能只有 imConversationID）
    id: primary.id?.trim() || secondary.id?.trim() || primary.id || secondary.id || '',
    from: pickPreferredName(primary.from, secondary.from) || primary.from,
    to: pickPreferredName(primary.to, secondary.to) || primary.to,
    imConversationID: primary.imConversationID?.trim() || secondary.imConversationID,
    fromAgentId: primary.fromAgentId || secondary.fromAgentId,
    fromAgentAccount: primary.fromAgentAccount || secondary.fromAgentAccount,
    actorPlatformID: primary.actorPlatformID || secondary.actorPlatformID,
    actorPlatformNickname: primary.actorPlatformNickname || secondary.actorPlatformNickname,
    actorPlatformFaceURL: primary.actorPlatformFaceURL || secondary.actorPlatformFaceURL,
    audiencePlatformNickname: primary.audiencePlatformNickname || secondary.audiencePlatformNickname,
    audiencePlatformFaceURL: primary.audiencePlatformFaceURL || secondary.audiencePlatformFaceURL,
    lastMessage: primary.lastMessage ?? secondary.lastMessage,
    preview: primary.preview || secondary.preview,
    time: primary.time || secondary.time,
    proactiveActionHints: primary.proactiveActionHints?.length
      ? primary.proactiveActionHints
      : secondary.proactiveActionHints,
    taskMode: primary.taskMode ?? secondary.taskMode,
    skillGroup: primary.skillGroup ?? secondary.skillGroup,
    handledAdoptionID: primary.handledAdoptionID ?? secondary.handledAdoptionID,
    adoptionContext:
      pickValidAdoptionContext(primary.adoptionContext) ??
      pickValidAdoptionContext(secondary.adoptionContext),
    redDotAckServerMsgID: primary.redDotAckServerMsgID || secondary.redDotAckServerMsgID,
  };
}

/**
 * 去掉因主键不一致产生的重复行（如一边只有 taskID、一边有 imConversationID）。
 * 保持相对顺序：首次出现位置保留合并结果。
 */
export function dedupeConversationsByIdentity(list: MockConversation[]): MockConversation[] {
  const result: MockConversation[] = [];
  const indexByIm = new Map<string, number>();
  const indexByTask = new Map<string, number>();

  const resolveIndex = (item: MockConversation): number => {
    const im = item.imConversationID?.trim();
    const id = item.id?.trim();
    if (im && indexByIm.has(im)) return indexByIm.get(im)!;
    if (id && indexByTask.has(id)) return indexByTask.get(id)!;
    return -1;
  };

  const register = (item: MockConversation, idx: number) => {
    const im = item.imConversationID?.trim();
    const id = item.id?.trim();
    if (im) indexByIm.set(im, idx);
    if (id) indexByTask.set(id, idx);
  };

  for (const item of list) {
    const idx = resolveIndex(item);
    if (idx < 0) {
      const newIdx = result.length;
      result.push(item);
      register(item, newIdx);
      continue;
    }
    const merged = mergeConversationPair(result[idx], item);
    result[idx] = merged;
    register(merged, idx);
  }
  return result;
}

/** 会话排序时间：优先 lastMessage.sendTime；无效返回 null（排到分区末尾） */
export function getConversationSortTime(c: MockConversation): number | null {
  const t = c.lastMessage?.sendTime;
  if (t == null || t === 0 || !Number.isFinite(t)) return null;
  const ms = normalizeSendTimeMs(t);
  return ms > 0 ? ms : null;
}

/** 同一分区内按 lastMessage 时间倒序 */
function compareByLastMessageDesc(a: MockConversation, b: MockConversation): number {
  const ta = getConversationSortTime(a);
  const tb = getConversationSortTime(b);
  if (ta == null && tb == null) return 0;
  if (ta == null) return 1;
  if (tb == null) return -1;
  return tb - ta;
}

/** 同一条末条消息（serverMsgID + 归一化时间一致即视为同一条） */
function isSameLastMessage(
  a: MockConversation['lastMessage'],
  b: MockConversation['lastMessage'],
): boolean {
  if (a === b) return true;
  if (!a || !b) return false;
  if ((a.serverMsgID ?? '') !== (b.serverMsgID ?? '')) return false;
  return normalizeSendTimeMs(a.sendTime ?? 0) === normalizeSendTimeMs(b.sendTime ?? 0);
}

/**
 * 会话内容是否等价。
 * 缺失键与 undefined 视为相等（缓存 JSON 往返会丢掉 undefined 键）；
 * lastMessage / adoptionContext 按业务主键比，避免每次接口映射生成新对象就判不等。
 */
function isEquivalentConversation(a: MockConversation, b: MockConversation): boolean {
  if (a === b) return true;
  const ar = a as unknown as Record<string, unknown>;
  const br = b as unknown as Record<string, unknown>;
  const keys = new Set([...Object.keys(ar), ...Object.keys(br)]);
  for (const key of keys) {
    const av = ar[key];
    const bv = br[key];
    if (av === bv) continue;
    if (key === 'lastMessage') {
      if (isSameLastMessage(a.lastMessage, b.lastMessage)) continue;
      return false;
    }
    if (key === 'adoptionContext') {
      const aid = pickValidAdoptionContext(a.adoptionContext)?.adoptionID?.trim() || '';
      const bid = pickValidAdoptionContext(b.adoptionContext)?.adoptionID?.trim() || '';
      if (aid === bid) continue;
      return false;
    }
    return false;
  }
  return true;
}

/**
 * 本地与 claimed/list 映射结果合并：
 * - remote 为权威：taskMode 等字段对齐本次 list
 * - 若本地 lastMessage 比 list 更新（WS/退出回写先行），保留本地预览/时间，避免刷新瞬时回退乱序
 * - 纯本地字段（主管接管来源账号、红点水位）：保留 local
 * - hasRedDot：用末条 + redDotAckServerMsgID 重算，禁止被 list「仅 direction=0」整份覆盖
 * - 合并结果与 local 等价时返回 local 原对象，让列表行的 memo 生效（轮询刷新不再整表重绘）
 */
function mergeOne(local: MockConversation, remote: MockConversation): MockConversation {
  const localTs = getConversationSortTime(local);
  const remoteTs = getConversationSortTime(remote);
  const keepLocalLast =
    localTs != null && (remoteTs == null || localTs > remoteTs) && !!local.lastMessage;

  const lastMessage = keepLocalLast ? local.lastMessage : remote.lastMessage;
  const redDotAckServerMsgID = local.redDotAckServerMsgID;
  const hasRedDot = resolveConversationHasRedDot({
    lastMessage,
    redDotAckServerMsgID,
  });

  const adoptionContext = resolveAdoptionContextOnClaimedMerge(local, remote);

  const merged: MockConversation = {
    // list 映射结果整份为准（勿 ...local 再挑字段，否则会残留过期 taskMode 等）
    ...remote,
    // claimed/list 命中＝当前账号自己的任务
    supervisorTakeover: false,
    returnedToAgent: false,
    inactive: false,
    // 接口不返回 → 保留本地扩展
    fromAgentId: local.fromAgentId,
    fromAgentAccount: local.fromAgentAccount,
    // claimed/list 不一定带 skillGroup，缺省时保留 tasks/detail 写入的值
    skillGroup: remote.skillGroup ?? local.skillGroup,
    // list 某次没带 session.actor* 时不要把本地已写入的身份冲掉（置灰后 list 不再回填）
    actorPlatformID: remote.actorPlatformID || local.actorPlatformID,
    actorPlatformNickname: remote.actorPlatformNickname || local.actorPlatformNickname,
    actorPlatformFaceURL: remote.actorPlatformFaceURL || local.actorPlatformFaceURL,
    audiencePlatformID: remote.audiencePlatformID || local.audiencePlatformID,
    audiencePlatformNickname: remote.audiencePlatformNickname || local.audiencePlatformNickname,
    audiencePlatformFaceURL: remote.audiencePlatformFaceURL || local.audiencePlatformFaceURL,
    // claimed/list 不返回复审水位：始终保留本地已处理的 adoptionID
    handledAdoptionID: local.handledAdoptionID,
    // adoptionContext：未 handled 才用 list 更新，已 handled 一定不覆盖
    ...(adoptionContext ? { adoptionContext } : { adoptionContext: undefined }),
    redDotAckServerMsgID,
    hasRedDot,
    proactiveActionHints: local.proactiveActionHints,
    ...(keepLocalLast
      ? {
          lastMessage: local.lastMessage,
          preview: local.preview,
          time: local.time,
        }
      : null),
  };

  return isEquivalentConversation(local, merged) ? local : merged;
}

export type MergeClaimedResult = {
  /** 会话库：active + history（包含 inactive 标记） */
  all: MockConversation[];
  /** UI 列表：active 在上，history 在下；各区按时间倒序 */
  ui: MockConversation[];
};

/**
 * active 在上、history 在下；各区内按 lastMessage.sendTime 倒序。
 * 所有列表写盘/展示出口应走此函数，避免仅 bump 导致的相对顺序漂移。
 */
/**
 * claimed/list 刷新与 WS 增量并发时，把最新内存里接口不返回的 ephemeral 字段合并回去。
 * 避免 refresh 赋值覆盖刚写入的 proactiveActionHints / adoptionContext / 复审已处理水位。
 */
export function preserveEphemeralLocalFields(
  latestLocal: MockConversation[],
  merged: MockConversation[],
): MockConversation[] {
  if (latestLocal.length === 0) return merged;
  const localIndex = buildConversationIdentityIndex(latestLocal);
  let changed = false;
  const next = merged.map((item) => {
    const idx = lookupConversationIndex(localIndex, item);
    if (idx < 0) return item;
    const src = latestLocal[idx];
    const proactiveActionHints = src.proactiveActionHints?.length
      ? src.proactiveActionHints
      : item.proactiveActionHints;
    const handledAdoptionID = item.handledAdoptionID || src.handledAdoptionID;
    const adoptionContext = resolvePreservedAdoptionContext(
      { ...item, handledAdoptionID },
      src,
    );
    const sameHints = proactiveActionHints === item.proactiveActionHints;
    const sameHandled = handledAdoptionID === item.handledAdoptionID;
    const sameAdoption =
      (adoptionContext?.adoptionID || undefined) === (item.adoptionContext?.adoptionID || undefined) &&
      !!pickValidAdoptionContext(adoptionContext) === !!pickValidAdoptionContext(item.adoptionContext);
    if (sameHints && sameHandled && sameAdoption) {
      return item;
    }
    changed = true;
    const patched: MockConversation = {
      ...item,
      ...(proactiveActionHints?.length ? { proactiveActionHints } : null),
      ...(handledAdoptionID ? { handledAdoptionID } : null),
    };
    if (adoptionContext) {
      patched.adoptionContext = adoptionContext;
    } else {
      delete patched.adoptionContext;
    }
    return patched;
  });
  return changed ? next : merged;
}

export function buildClaimedUIList(all: MockConversation[]): MockConversation[] {
  const deduped = dedupeConversationsByIdentity(all);
  const active: MockConversation[] = [];
  const history: MockConversation[] = [];
  for (const c of deduped) {
    if (c.inactive) history.push(c);
    else active.push(c);
  }
  active.sort(compareByLastMessageDesc);
  history.sort(compareByLastMessageDesc);
  return [...active, ...history];
}

/**
 * 将本次 claimed/list（remoteActive）合并到本地会话库（localAll）：
 * - remoteActive 中存在的会话：整份以 list 为准更新；inactive=false、接管/归还标记清零
 * - localAll 中但 remoteActive 不存在：inactive=true（历史/无权限）
 * - 匹配时 imConversationID / taskID 任一命中即可，避免接管 upsert 与 list 主键不一致产生双行
 */
export function mergeClaimedConversations(
  localAll: MockConversation[],
  remoteActive: MockConversation[],
): MergeClaimedResult {
  const consumedLocal = new Set<number>();
  const active: MockConversation[] = [];
  const localIndex = buildConversationIdentityIndex(localAll);
  // 主键写法不一致时，仍要认出「已并入 active」的本地行，否则会被重复置灰
  const activeImIds = new Set<string>();
  const activeTaskIds = new Set<string>();

  for (const r of remoteActive) {
    const localIdx = lookupConversationIndex(localIndex, r);
    let merged: MockConversation;
    if (localIdx >= 0) {
      consumedLocal.add(localIdx);
      merged = mergeOne(localAll[localIdx], r);
    } else {
      merged = { ...r, supervisorTakeover: false, returnedToAgent: false, inactive: false };
    }
    active.push(merged);
    const im = merged.imConversationID?.trim();
    if (im) activeImIds.add(im);
    if (merged.id) activeTaskIds.add(merged.id);
  }

  const history: MockConversation[] = [];
  for (let i = 0; i < localAll.length; i++) {
    if (consumedLocal.has(i)) continue;
    const local = localAll[i];
    const localIm = local.imConversationID?.trim();
    if (localIm && activeImIds.has(localIm)) continue;
    if (local.id && activeTaskIds.has(local.id)) continue;
    history.push(local.inactive ? local : { ...local, inactive: true });
  }

  const ui = buildClaimedUIList([...active, ...history]);
  return { all: ui, ui };
}
