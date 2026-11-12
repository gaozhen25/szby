// ============================================================
// ai_review_required 时效校验（端侧共用）
// lastTriggerMsgID 与会话末条 serverMsgID 不一致 → 过时弃用
// ============================================================

import { imWarn } from '@/core/im/utils';
import type { MockConversation } from '@/mock/data';
import { findConversationIndexByIdentity } from '@/lib/claimed-conversations-merge';

export type AiReviewStaleCheckInput = {
  lastTriggerMsgID?: string | null;
  /** 会话末条 lastMessage.serverMsgID（列表缓存或聊天页末条） */
  convLastServerMsgID?: string | null;
  taskID?: string | null;
  imConversationID?: string | null;
};

/**
 * 从会话列表取 lastMessage.serverMsgID；找不到或没有末条则返回 null。
 */
export function pickConversationLastServerMsgID(
  list: MockConversation[],
  match: { taskID?: string | null; imConversationID?: string | null },
): string | null {
  const idx = findConversationIndexByIdentity(list, {
    imConversationID: match.imConversationID ?? undefined,
    id: match.taskID?.trim() || '',
  });
  if (idx < 0) return null;
  return list[idx]?.lastMessage?.serverMsgID?.trim() || null;
}

/**
 * lastTriggerMsgID 有值且会话末条 serverMsgID 也有值时：二者必须一致；
 * 不一致视为过时。任一侧为空则不过滤（避免列表尚未写入末条时误杀）。
 */
export function isStaleAiReviewRequired(input: AiReviewStaleCheckInput): boolean {
  const lastTriggerMsgID = input.lastTriggerMsgID?.trim() || '';
  if (!lastTriggerMsgID) return false;
  const convLast = input.convLastServerMsgID?.trim() || '';
  if (!convLast) return false;
  return convLast !== lastTriggerMsgID;
}

/**
 * 过时时打 warn（console + WS 导出日志），返回 true 表示应弃用、不再继续处理。
 */
export function discardIfStaleAiReviewRequired(
  input: AiReviewStaleCheckInput,
  meta?: Record<string, unknown>,
): boolean {
  const lastTriggerMsgID = input.lastTriggerMsgID?.trim() || '';
  if (!lastTriggerMsgID) return false;

  const convLastServerMsgID = input.convLastServerMsgID?.trim() || null;
  if (!isStaleAiReviewRequired({ ...input, lastTriggerMsgID, convLastServerMsgID })) {
    return false;
  }

  imWarn('AI复审', 'ai_review_required 已过时，已弃用（lastTriggerMsgID ≠ 会话末条 serverMsgID）', {
    lastTriggerMsgID,
    convLastServerMsgID,
    taskID: input.taskID ?? null,
    imConversationID: input.imConversationID ?? null,
    ...meta,
  });
  return true;
}
