// ============================================================
// 主管接管 / 客服被接管：纯函数补丁 + 兜底会话构建
// - 列表写盘一律经 ClaimedConversationsStore（禁止本文件直写 AsyncStorage 全量）
// - 客服被接管（ownership_changed）：置灰 + supervisorTakeover
// - 主管归还成功：returnedToAgent 标记
// ============================================================
import type { MockConversation } from '@/mock/data';
import { detectChatPlatform } from '@/core/im';
import { TASK_AVATAR_PALETTE } from '@/lib/task-session-list';
import {
  scheduleMutateClaimedConversationsCache,
  type ClaimedConversationsScope,
} from '@/lib/claimed-conversations-cache';
import {
  findConversationIndexByIdentity,
  isPlaceholderConversationName,
  mergeConversationPair,
} from '@/lib/claimed-conversations-merge';

/** 接管结果 / 归属变更事件里携带的富 task_context（比 IMTaskContext 更全） */
export interface TakeoverTaskContext {
  taskID: string;
  threadID?: string;
  sessionID?: string;
  imConversationID?: string;
  actorPlatformID?: string;
  audiencePlatformID?: string;
  actorPlatformNickname?: string;
  audiencePlatformNickname?: string;
  actorPlatformFaceURL?: string;
  audiencePlatformFaceURL?: string;
}

/** 事件富 task_context → MockConversation（拉不到 admin 任务详情时的兜底构建） */
export function contextToTakeoverConversation(
  ctx: TakeoverTaskContext,
  idx: number,
  meta: { fromAgentId?: string; fromAgentAccount?: string } = {},
): MockConversation {
  const taskID = (ctx.taskID ?? '').trim();
  const imConversationID = (ctx.imConversationID ?? '').trim();
  const platform = detectChatPlatform(imConversationID, ctx.audiencePlatformID || '');
  const actorName = ctx.actorPlatformNickname?.trim() || ctx.actorPlatformID || '教练';
  const audienceName = ctx.audiencePlatformNickname?.trim() || ctx.audiencePlatformID || '学员';
  return {
    id: taskID,
    from: actorName,
    to: audienceName,
    platform,
    time: '',
    avatarColor: TASK_AVATAR_PALETTE[idx % TASK_AVATAR_PALETTE.length],
    preview: '',
    unread: 0,
    categoryId: 'all',
    imConversationID,
    inactive: false,
    actorPlatformID: ctx.actorPlatformID?.trim() || undefined,
    actorPlatformNickname: ctx.actorPlatformNickname?.trim() || '',
    actorPlatformFaceURL: ctx.actorPlatformFaceURL?.trim() || undefined,
    audiencePlatformNickname: ctx.audiencePlatformNickname?.trim() || '',
    audiencePlatformFaceURL: ctx.audiencePlatformFaceURL?.trim() || undefined,
    audiencePlatformID: ctx.audiencePlatformID?.trim() || undefined,
    fromAgentId: meta.fromAgentId,
    fromAgentAccount: meta.fromAgentAccount,
    returnedToAgent: false,
  };
}

/**
 * 以 imConversationID 或 taskID 匹配后 upsert。
 * 避免 admin 详情缺 imConversationID、list 有完整主键时插入第二条「教练→学员」。
 * 兜底昵称不会覆盖列表已有真实昵称。
 */
export function upsertConversation(
  list: MockConversation[],
  conv: MockConversation,
): MockConversation[] {
  const idx = findConversationIndexByIdentity(list, conv);
  if (idx < 0) return [conv, ...list];
  const prev = list[idx];
  // 若新行几乎是占位会话，只补 fromAgent* / 缺省主键，不整行冲掉
  const incomingMostlyPlaceholder =
    isPlaceholderConversationName(conv.from) && isPlaceholderConversationName(conv.to);
  const merged = incomingMostlyPlaceholder
    ? {
        ...prev,
        id: (conv.id?.trim() || prev.id?.trim() || '') || prev.id,
        imConversationID: conv.imConversationID?.trim() || prev.imConversationID,
        fromAgentId: conv.fromAgentId || prev.fromAgentId,
        fromAgentAccount: conv.fromAgentAccount || prev.fromAgentAccount,
        returnedToAgent: false,
        inactive: false,
        supervisorTakeover: false,
      }
    : mergeConversationPair(prev, { ...conv, inactive: false, returnedToAgent: false, supervisorTakeover: false });
  const next = [...list];
  next[idx] = merged;
  return next;
}

/**
 * 客服端：会话被主管接管 → 置灰对应会话、打上 supervisorTakeover，并重排到 history 区顶部。
 * 主键匹配优先 imConversationID，兜底 taskID。
 * 无匹配时返回原数组（引用不变）。
 */
export function applySupervisorTakeoverToConversations(
  conversations: MockConversation[],
  params: { taskID?: string; imConversationID?: string },
): MockConversation[] {
  const { taskID, imConversationID } = params;
  const idx = conversations.findIndex((c) => {
    if (imConversationID && c.imConversationID === imConversationID) return true;
    if (taskID && c.id === taskID) return true;
    return false;
  });
  if (idx < 0) {
    console.log('[SupervisorTakeover] 会话列表未匹配到会话，跳过标记', {
      taskID,
      imConversationID,
      count: conversations.length,
    });
    return conversations;
  }

  const cur = conversations[idx];
  const patched =
    cur.inactive && cur.supervisorTakeover
      ? cur
      : { ...cur, inactive: true, supervisorTakeover: true as const };
  const rest = conversations.filter((_, i) => i !== idx);
  const active = rest.filter((c) => !c.inactive);
  const history = rest.filter((c) => c.inactive);
  // 被接管会话移到 history 区顶部（紧接 active 之后）
  const next = [...active, patched, ...history];
  const unchanged =
    patched === cur &&
    next.length === conversations.length &&
    next.every((c, i) => c === conversations[i]);
  if (unchanged) return conversations;

  console.log('[SupervisorTakeover] 已标记 supervisorTakeover 并重排', {
    taskID: patched.id,
    imConversationID: patched.imConversationID,
    from: patched.from,
    to: patched.to,
  });
  return next;
}

/**
 * 客服端：主管归还会话（return_to_agent）→ 清除 supervisorTakeover / inactive，并重排回 active 区顶部。
 * 主键匹配优先 imConversationID，兜底 taskID。无匹配时返回原数组。
 */
export function clearSupervisorTakeoverFromConversations(
  conversations: MockConversation[],
  params: { taskID?: string; imConversationID?: string },
): MockConversation[] {
  const { taskID, imConversationID } = params;
  const idx = conversations.findIndex((c) => {
    if (imConversationID && c.imConversationID === imConversationID) return true;
    if (taskID && c.id === taskID) return true;
    return false;
  });
  if (idx < 0) return conversations;

  const cur = conversations[idx];
  if (!cur.supervisorTakeover && !cur.inactive) return conversations;

  const patched = { ...cur, inactive: false, supervisorTakeover: false };
  const rest = conversations.filter((_, i) => i !== idx);
  const active = rest.filter((c) => !c.inactive);
  const history = rest.filter((c) => c.inactive);
  const next = [patched, ...active, ...history];
  console.log('[SupervisorTakeover] 已清除 supervisorTakeover（归还给客服）并重排', {
    taskID: patched.id,
    imConversationID: patched.imConversationID,
  });
  return next;
}

/**
 * 主管端：归还成功（supervisor_return_to_agent_result ok）→
 * 打上 returnedToAgent、置灰并重排到 history 区顶部。
 */
export function applyReturnedToAgentToConversations(
  conversations: MockConversation[],
  params: { taskID?: string; imConversationID?: string },
): MockConversation[] {
  const { taskID, imConversationID } = params;
  const idx = conversations.findIndex((c) => {
    if (imConversationID && c.imConversationID === imConversationID) return true;
    if (taskID && c.id === taskID) return true;
    return false;
  });
  if (idx < 0) {
    console.log('[SupervisorTakeover] 归还标记未匹配到会话，跳过', {
      taskID,
      imConversationID,
      count: conversations.length,
    });
    return conversations;
  }

  const cur = conversations[idx];
  const patched =
    cur.inactive && cur.returnedToAgent
      ? cur
      : {
          ...cur,
          inactive: true,
          returnedToAgent: true as const,
          supervisorTakeover: false,
        };
  const rest = conversations.filter((_, i) => i !== idx);
  const active = rest.filter((c) => !c.inactive);
  const history = rest.filter((c) => c.inactive);
  const next = [...active, patched, ...history];
  const unchanged =
    patched === cur &&
    next.length === conversations.length &&
    next.every((c, i) => c === conversations[i]);
  if (unchanged) return conversations;

  console.log('[SupervisorTakeover] 已标记 returnedToAgent 并重排', {
    taskID: patched.id,
    imConversationID: patched.imConversationID,
  });
  return next;
}

/** 主管端：归还成功后写入本地会话缓存（内存未命中时回退写盘） */
export function scheduleReturnedToAgentCache(
  scope: ClaimedConversationsScope,
  params: { taskID?: string; imConversationID?: string },
): void {
  scheduleMutateClaimedConversationsCache(
    scope,
    (list) => {
      const patched = applyReturnedToAgentToConversations(list, params);
      return patched !== list ? patched : null;
    },
    'supervisor_return_to_agent',
  );
}
