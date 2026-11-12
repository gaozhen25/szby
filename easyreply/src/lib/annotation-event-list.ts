// ============================================================
// annotation_event → 会话列表本地增量更新
// - eventType=1：新消息 / 红点
// - eventType=2|3：任务回收置灰
// - eventType=5：主动触达提醒（黄点 + proactiveActionHints）
// - eventType=8：AI 复审 → 写入会话实体 adoptionContext（列表标识 + 进房读缓存）
// ============================================================
import type { MockConversation } from '@/mock/data';
import type {
  AdoptionContext,
  IMAnnotationEventPayload,
  IMServerMessage,
  ProactiveActionHint,
} from '@/core/im/types';
import { normalizeSendTimeMs, parseApiMessageContent, preserveServerMessageForCache } from '@/core/im/utils';
import { isConversationOwnedAndActive } from '@/chatMessage/room/chat-input-gate';
import { buildClaimedUIList, findConversationIndexByIdentity } from '@/lib/claimed-conversations-merge';
import {
  extractProactiveActionHintsFromAnnotationEvent,
  isSameProactiveActionHint,
  mergeProactiveActionHints,
  pickValidProactiveActionHints,
} from '@/lib/proactive-action-hints';
import { formatTaskTriggerTime } from '@/lib/task-session-list';
import {
  resolveConversationHasRedDot,
  resolveRedDotAckServerMsgID,
} from '@/lib/conversation-red-dot';

/** 复审上下文是否含有候选（可展示） */
export function pickValidAdoptionContext(
  adoption?: AdoptionContext | null,
): AdoptionContext | undefined {
  if (!adoption || !Array.isArray(adoption.candidates) || adoption.candidates.length === 0) {
    return undefined;
  }
  return adoption;
}

/** 根据 contentType 生成列表预览文案 */
export function previewFromServerMessage(msg: IMServerMessage): string {
  if (msg.contentType === 102) return '[图片]';
  if (msg.contentType === 103) return '[语音]';
  if (msg.contentType === 104) return '[视频]';
  if (msg.contentType === 105) return '[文件]';
  if (msg.contentType === 109) return '[位置]';
  const text = parseApiMessageContent(msg.content);
  return text.trim() || '[消息]';
}

function findConversationIndex(
  conversations: MockConversation[],
  imConversationID?: string,
  taskID?: string,
): number {
  return findConversationIndexByIdentity(conversations, {
    imConversationID,
    id: taskID ?? '',
  });
}

/** active 在上、history 在下；各区内按 lastMessage.sendTime 倒序 */
export function sortConversationsByLastTrigger(
  conversations: MockConversation[],
): MockConversation[] {
  // 与会话列表统一出口一致（分区 + 时间倒序）
  return buildClaimedUIList(conversations);
}

/** 将会话置顶到对应分区（新消息→active 顶；回收/关闭→history 顶） */
function bumpConversation(
  conversations: MockConversation[],
  idx: number,
  patch: Partial<MockConversation>,
): MockConversation[] {
  const item = { ...conversations[idx], ...patch };
  const rest = conversations.filter((_, i) => i !== idx);
  const active = rest.filter((c) => !c.inactive);
  const history = rest.filter((c) => c.inactive);
  if (item.inactive) {
    return [...active, item, ...history];
  }
  return [item, ...active, ...history];
}

/**
 * 将 annotation_event 应用到会话列表：
 * - eventType=1：更新最新消息预览与时间，并置顶到 active 区
 * - eventType=2|3：任务已从当前客服会话中移除（回收/关闭）→ 置灰
 * - eventType=5：写入 proactiveActionHints（定时主动触达黄点）
 * - eventType=8：写入 adoptionContext（待 AI 复审；已 handled 则忽略）
 */
export function applyAnnotationEventToConversations(
  conversations: MockConversation[],
  evt: IMAnnotationEventPayload,
): MockConversation[] {
  const imConversationID = evt.task_context?.imConversationID;
  const taskID = evt.task_context?.taskID ?? evt.event?.taskID;
  const eventType = evt.event?.eventType;

  const idx = findConversationIndex(conversations, imConversationID, taskID);
  if (idx < 0) return conversations;

  if (eventType === 1) {
    const msg = evt.event?.message;
    if (!msg) return conversations;

    // 主管旁观（enter_thread 未接管）同样会收到消息事件。会话不属于自己时列表不该有任何变化：
    // 既不能把置灰历史会话顶回活跃，也不该刷新预览/红点。活跃与否只由 claimed/list 与归属事件决定。
    if (!isConversationOwnedAndActive(conversations[idx])) return conversations;

    const sendTime = normalizeSendTimeMs(
      msg.sendTime ?? evt.event?.eventTime ?? Date.now(),
    );

    const patch: Partial<MockConversation> = {
      preview: previewFromServerMessage(msg),
      time: formatTaskTriggerTime(sendTime),
      lastMessage: preserveServerMessageForCache(msg),
    };

    // 红点=对方末条且尚未处理到该 serverMsgID（与 redDotAckServerMsgID 水位比较）
    if (msg.direction === 0) {
      patch.hasRedDot = resolveConversationHasRedDot({
        lastMessage: msg,
        redDotAckServerMsgID: conversations[idx].redDotAckServerMsgID,
      });
    } else if (msg.direction === 1) {
      patch.hasRedDot = false;
      const ack = resolveRedDotAckServerMsgID(msg);
      if (ack) patch.redDotAckServerMsgID = ack;
    }

    return bumpConversation(conversations, idx, patch);
  }

  // 任务会话被回收（下班 / 超时重派等，无法继续聊天）：列表置灰并写本地缓存。
  // 回收只是任务暂时离手，主动触达待办仍未完成，保留 proactiveActionHints；
  // 置灰会话本就不计入黄点角标，重新认领后 merge 会把它带回来。
  if (eventType === 2 || eventType === 3) {
    return bumpConversation(conversations, idx, { inactive: true });
  }

  // 定时主动触达提醒：合并写入 proactiveActionHints（支持多条累积）
  if (eventType === 5) {
    const hints = extractProactiveActionHintsFromAnnotationEvent(evt);
    if (!hints) return conversations;
    const cur = conversations[idx];
    const merged = mergeProactiveActionHints(cur.proactiveActionHints, hints);
    if (!merged?.length) return conversations;
    const same =
      cur.proactiveActionHints?.length === merged.length &&
      cur.proactiveActionHints.every((h, i) => isSameProactiveActionHint(h, merged[i]!));
    if (same) return conversations;
    return bumpConversation(conversations, idx, {
      proactiveActionHints: merged,
      inactive: false,
    });
  }

  // AI 候选需人工复审：写入会话缓存 adoptionContext
  if (eventType === 8) {
    const patched = applyAdoptionContextToConversations(conversations, {
      imConversationID,
      taskID,
      adoptionContext: evt.event?.adoptionContext,
    });
    return patched ?? conversations;
  }

  return conversations;
}

/**
 * 写入待复审 adoptionContext（WS ai_review_required / eventType=8 / 进房补写）。
 * 已 handled 的 adoptionID 忽略；无匹配会话返回 null。
 */
export function applyAdoptionContextToConversations(
  conversations: MockConversation[],
  params: {
    imConversationID?: string;
    taskID?: string;
    adoptionContext?: AdoptionContext | null;
  },
): MockConversation[] | null {
  const adoption = pickValidAdoptionContext(params.adoptionContext);
  if (!adoption) return null;

  const idx = findConversationIndex(conversations, params.imConversationID, params.taskID);
  if (idx < 0) return null;

  const cur = conversations[idx];
  const adoptionID = adoption.adoptionID?.trim();
  if (adoptionID && cur.handledAdoptionID === adoptionID) return null;

  if (
    cur.adoptionContext?.adoptionID === adoption.adoptionID &&
    (cur.adoptionContext?.candidates?.length ?? 0) === (adoption.candidates?.length ?? 0)
  ) {
    // 同 ID 仍覆盖，避免候选内容变更时列表/进房读到旧稿
    const next = [...conversations];
    next[idx] = { ...cur, adoptionContext: adoption };
    return next;
  }

  const next = [...conversations];
  next[idx] = { ...cur, adoptionContext: adoption };
  return next;
}

/**
 * annotation_task_claimed：新认领任务 → 恢复 active（红点由 claimed/list 的 messages 决定，此处不改 hasRedDot）。
 * 无匹配返回 null。
 */
export function applyTaskClaimedToConversations(
  conversations: MockConversation[],
  match: { imConversationID?: string; taskID?: string },
): MockConversation[] | null {
  const idx = findConversationIndex(conversations, match.imConversationID, match.taskID);
  if (idx < 0) return null;

  const cur = conversations[idx];
  if (!cur.inactive && !cur.supervisorTakeover) return null;

  return bumpConversation(conversations, idx, {
    inactive: false,
    supervisorTakeover: false,
  });
}

/** 清除单条会话红点，并写入当时末条消息水位；无变化返回 null */
export function clearConversationRedDot(
  conversations: MockConversation[],
  match: { imConversationID?: string; taskID?: string },
): MockConversation[] | null {
  let changed = false;
  const next = conversations.map((c) => {
    const hit =
      (match.imConversationID && c.imConversationID === match.imConversationID) ||
      (match.taskID && c.id === match.taskID);
    if (!hit) return c;

    const ack = resolveRedDotAckServerMsgID(c.lastMessage);
    const nextAck = ack || c.redDotAckServerMsgID;
    if (!c.hasRedDot && (c.redDotAckServerMsgID || undefined) === (nextAck || undefined)) {
      return c;
    }
    changed = true;
    return {
      ...c,
      hasRedDot: false,
      ...(nextAck ? { redDotAckServerMsgID: nextAck } : null),
    };
  });
  return changed ? next : null;
}

/**
 * 用聊天页最后一条消息覆盖会话列表对应项的 lastMessage（按 imConversationID 匹配），
 * 并同步 preview / time 后置顶。
 * 无匹配、会话不属于自己或无变化返回 null。
 */
export function applyLastMessageToConversations(
  conversations: MockConversation[],
  params: { imConversationID: string; lastMessage: IMServerMessage },
): MockConversation[] | null {
  const imConversationID = params.imConversationID.trim();
  if (!imConversationID || !params.lastMessage) return null;

  const idx = conversations.findIndex((c) => c.imConversationID === imConversationID);
  if (idx < 0) return null;
  // 与 eventType=1 一致：旁观 / 已置灰 / 被接管的会话不回写列表
  if (!isConversationOwnedAndActive(conversations[idx])) return null;

  const msg = preserveServerMessageForCache(params.lastMessage);
  const sendTime = normalizeSendTimeMs(msg.sendTime);
  const preview = previewFromServerMessage(msg);
  const time = formatTaskTriggerTime(sendTime);
  const cur = conversations[idx];

  // 同一条消息且展示字段已一致则跳过
  if (
    cur.lastMessage?.serverMsgID &&
    cur.lastMessage.serverMsgID === msg.serverMsgID &&
    cur.preview === preview &&
    cur.time === time
  ) {
    return null;
  }

  const patch: Partial<MockConversation> = {
    lastMessage: msg,
    preview,
    time,
  };
  // 客服侧发出 → 视为已处理并抬升水位；对方发出 → 按水位判定是否亮红点
  if (msg.direction === 1) {
    patch.hasRedDot = false;
    const ack = resolveRedDotAckServerMsgID(msg);
    if (ack) patch.redDotAckServerMsgID = ack;
  } else if (msg.direction === 0) {
    patch.hasRedDot = resolveConversationHasRedDot({
      lastMessage: msg,
      redDotAckServerMsgID: cur.redDotAckServerMsgID,
    });
  }

  return bumpConversation(conversations, idx, patch);
}

/**
 * 更新会话 taskMode / skillGroup（set_task_mode_result / tasks/detail）。
 * 按 imConversationID 优先、taskID 兜底匹配；无匹配或无变化返回 null。
 */
export function applyTaskModeToConversations(
  conversations: MockConversation[],
  params: {
    taskID?: string;
    imConversationID?: string;
    taskMode: 'human' | 'ai_assisted';
    /** tasks/detail 才带；set_task_mode_result 不带时保留原值 */
    skillGroup?: string;
  },
): MockConversation[] | null {
  const { taskMode } = params;
  if (taskMode !== 'human' && taskMode !== 'ai_assisted') return null;

  const idx = findConversationIndex(conversations, params.imConversationID, params.taskID);
  if (idx < 0) return null;

  const cur = conversations[idx];
  const skillGroup = params.skillGroup?.trim() || cur.skillGroup;
  if (cur.taskMode === taskMode && cur.skillGroup === skillGroup) return null;

  const next = [...conversations];
  next[idx] = { ...cur, taskMode, ...(skillGroup ? { skillGroup } : null) };
  return next;
}

/**
 * 记录该会话已复审过的 adoptionID，并清除缓存中的 adoptionContext。
 * 主键优先 imConversationID，兜底 taskID；无匹配或水位未变且已无 pending 返回 null。
 */
export function applyHandledAdoptionIDToConversations(
  conversations: MockConversation[],
  params: { imConversationID?: string; taskID?: string; adoptionID?: string },
): MockConversation[] | null {
  const adoptionID = params.adoptionID?.trim();
  if (!adoptionID) return null;

  const idx = findConversationIndex(conversations, params.imConversationID, params.taskID);
  if (idx < 0) return null;

  const cur = conversations[idx];
  const hadPending = !!pickValidAdoptionContext(cur.adoptionContext);
  if (cur.handledAdoptionID === adoptionID && !hadPending) return null;

  const next = [...conversations];
  const { adoptionContext: _cleared, ...rest } = cur;
  next[idx] = { ...rest, handledAdoptionID: adoptionID };
  return next;
}

/**
 * 将会话置灰（任务完成 / 回收等）。
 * 主键优先 imConversationID，兜底 taskID；无匹配或已 inactive 返回 null。
 */
export function applyInactiveToConversations(
  conversations: MockConversation[],
  params: { imConversationID?: string; taskID?: string },
): MockConversation[] | null {
  const idx = findConversationIndex(conversations, params.imConversationID, params.taskID);
  if (idx < 0) return null;

  const cur = conversations[idx];
  if (cur.inactive && !cur.proactiveActionHints?.length) return null;

  return bumpConversation(conversations, idx, {
    inactive: true,
    proactiveActionHints: undefined,
  });
}

/**
 * 清除会话 proactiveActionHints（用户关闭主动触达提醒后）。
 * 无匹配或本无该字段返回 null。
 */
export function clearProactiveActionHintsFromConversations(
  conversations: MockConversation[],
  params: { imConversationID?: string; taskID?: string },
): MockConversation[] | null {
  const idx = findConversationIndex(conversations, params.imConversationID, params.taskID);
  if (idx < 0) return null;

  const cur = conversations[idx];
  if (!cur.proactiveActionHints?.length) return null;

  const next = [...conversations];
  const { proactiveActionHints: _removed, ...rest } = cur;
  next[idx] = rest;
  return next;
}

/**
 * 更新会话 proactiveActionHints（发送单条后移除剩余提醒等）。
 * hints 为空时等价于清除。
 */
export function setProactiveActionHintsOnConversation(
  conversations: MockConversation[],
  params: {
    imConversationID?: string;
    taskID?: string;
    hints: ProactiveActionHint[];
  },
): MockConversation[] | null {
  const idx = findConversationIndex(conversations, params.imConversationID, params.taskID);
  if (idx < 0) return null;

  const valid = pickValidProactiveActionHints(params.hints);
  const cur = conversations[idx];
  if (!valid?.length) {
    return clearProactiveActionHintsFromConversations(conversations, params);
  }
  if (
    cur.proactiveActionHints?.length === valid.length &&
    cur.proactiveActionHints.every((h, i) => isSameProactiveActionHint(h, valid[i]!))
  ) {
    return null;
  }

  const next = [...conversations];
  next[idx] = { ...cur, proactiveActionHints: valid };
  return next;
}
