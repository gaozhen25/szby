// ============================================================
// 会话「已处理」事件总线（跨屏幕通知清除红点）
// - 聊天详情页回复/点击已处理 → emit
// - 会话列表订阅 → 清除对应会话红点，并写入 redDotAckServerMsgID 水位
// ============================================================

export type ConversationProcessedPayload = {
  taskID?: string;
  imConversationID?: string;
};

type Listener = (payload: ConversationProcessedPayload) => void;

const listeners = new Set<Listener>();

/** 通知某会话已被处理（回复或点击已处理） */
export function emitConversationProcessed(payload: ConversationProcessedPayload): void {
  for (const l of listeners) {
    try {
      l(payload);
    } catch {
      // 单个监听器异常不影响其他监听器
    }
  }
}

/** 订阅会话已处理事件，返回取消订阅函数 */
export function subscribeConversationProcessed(cb: Listener): () => void {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}
