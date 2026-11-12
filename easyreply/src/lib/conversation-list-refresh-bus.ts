// ============================================================
// 会话列表手动刷新完成 → 通知当前打开的聊天页同步重拉
// ============================================================

type Listener = () => void;

const listeners = new Set<Listener>();

/** 会话列表手动刷新完成后派发 */
export function emitConversationListManualRefreshed(): void {
  for (const l of listeners) {
    try {
      l();
    } catch {
      // 单个监听器异常不影响其他监听器
    }
  }
}

/** 订阅会话列表手动刷新完成，返回取消订阅函数 */
export function subscribeConversationListManualRefresh(cb: Listener): () => void {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}
