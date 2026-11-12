// ============================================================
// 会话列表红点判定
// - 红点 ≠ 未读：进入会话查看不会清；需回复 /「已处理」才清
// - 仅「最后一条是对方(direction=0)」不够：已处理后 claimed/list 仍可能是对方末条，
//   会把本地 hasRedDot=false 又盖回 true
// - 水位 redDotAckServerMsgID：清除红点时记下当时 lastMessage.serverMsgID；
//   仅当对方末条 serverMsgID 与水位不同（新消息）时再亮红点
// ============================================================
import type { IMServerMessage } from '@/core/im';

/** 根据末条消息 + 已处理水位计算是否应显示红点 */
export function resolveConversationHasRedDot(params: {
  lastMessage?: IMServerMessage | null;
  redDotAckServerMsgID?: string | null;
}): boolean {
  const last = params.lastMessage;
  if (!last || last.direction !== 0) return false;
  const msgId = last.serverMsgID?.trim();
  if (!msgId) return true;
  const ack = params.redDotAckServerMsgID?.trim();
  if (!ack) return true;
  return msgId !== ack;
}

/** 清除红点时写入的水位：取当时会话末条消息 id（通常为对方刚发的那条） */
export function resolveRedDotAckServerMsgID(
  lastMessage?: IMServerMessage | null,
): string | undefined {
  const id = lastMessage?.serverMsgID?.trim();
  return id || undefined;
}
