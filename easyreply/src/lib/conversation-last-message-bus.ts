// ============================================================
// 聊天页末条 → 会话列表
// - 发送/接收导致末条变化时 schedule（按 imConversationID 合并，短窗口防抖）
// - 退房 / 切会话时 flush，避免防抖窗口内的末条丢失
// - 会话列表订阅 → 覆盖 lastMessage + 刷新 preview/time + 写本地缓存
// ============================================================
import type { IMServerMessage } from '@/core/im/types';

export type ConversationLastMessagePayload = {
  imConversationID: string;
  lastMessage: IMServerMessage;
};

type Listener = (payload: ConversationLastMessagePayload) => void;

/** 同一会话连续末条合并窗口；到期一次派发，避免列表跟着每条消息重绘 */
export const CONVERSATION_LAST_MESSAGE_DEBOUNCE_MS = 280;

const listeners = new Set<Listener>();
const pending = new Map<string, ConversationLastMessagePayload>();
let flushTimer: ReturnType<typeof setTimeout> | null = null;

function dispatch(payload: ConversationLastMessagePayload): void {
  for (const l of listeners) {
    try {
      l(payload);
    } catch {
      // 单个监听器异常不影响其他监听器
    }
  }
}

function flushPending(): void {
  if (flushTimer != null) {
    clearTimeout(flushTimer);
    flushTimer = null;
  }
  if (pending.size === 0) return;
  const batch = [...pending.values()];
  pending.clear();
  for (const payload of batch) dispatch(payload);
}

/** 立即通知会话列表：用聊天页最后一条消息覆盖对应会话 */
export function emitConversationLastMessage(payload: ConversationLastMessagePayload): void {
  const imConversationID = payload.imConversationID.trim();
  if (!imConversationID || !payload.lastMessage) return;
  pending.delete(imConversationID);
  dispatch({ imConversationID, lastMessage: payload.lastMessage });
}

/**
 * 防抖通知会话列表。同一会话只保留最新一条；窗口内多会话合并为一次 flush。
 * 定时器不随后续消息重置，保证持续收发时列表仍会在窗口结束时刷新。
 */
export function scheduleConversationLastMessage(payload: ConversationLastMessagePayload): void {
  const imConversationID = payload.imConversationID.trim();
  if (!imConversationID || !payload.lastMessage) return;
  pending.set(imConversationID, { imConversationID, lastMessage: payload.lastMessage });
  if (flushTimer != null) return;
  flushTimer = setTimeout(() => {
    flushTimer = null;
    flushPending();
  }, CONVERSATION_LAST_MESSAGE_DEBOUNCE_MS);
}

/** 立即派发指定会话（或全部）尚未发出的末条 */
export function flushConversationLastMessage(
  imConversationID?: string,
  lastMessage?: IMServerMessage,
): void {
  const id = imConversationID?.trim();
  if (!id) {
    if (lastMessage) return;
    flushPending();
    return;
  }
  if (lastMessage) {
    pending.set(id, { imConversationID: id, lastMessage });
  }
  const payload = pending.get(id);
  pending.delete(id);
  if (pending.size === 0 && flushTimer != null) {
    clearTimeout(flushTimer);
    flushTimer = null;
  }
  if (payload) dispatch(payload);
}

/** 订阅聊天页回传的 lastMessage，返回取消订阅函数 */
export function subscribeConversationLastMessage(cb: Listener): () => void {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}
