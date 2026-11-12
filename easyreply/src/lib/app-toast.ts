// ============================================================
// 跨端轻量 Toast（顶部短暂提示）
// listeners 挂 globalThis，避免静态导出分包导致「发/订」不是同一份 Set
// ============================================================

export type AppToastPayload = {
  id: number;
  message: string;
  /** 持续毫秒，默认 2000 */
  duration?: number;
  /** 语义：default / danger / success，决定配色 */
  variant?: 'default' | 'danger' | 'success';
};

type Listener = (payload: AppToastPayload | null) => void;

const GLOBAL_KEY = '__qinghui_app_toast_listeners__';
const CURRENT_KEY = '__qinghui_app_toast_current__';

function getListeners(): Set<Listener> {
  const g = globalThis as typeof globalThis & { [GLOBAL_KEY]?: Set<Listener> };
  if (!g[GLOBAL_KEY]) g[GLOBAL_KEY] = new Set();
  return g[GLOBAL_KEY]!;
}

export function subscribeAppToast(listener: Listener): () => void {
  const listeners = getListeners();
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function emit(payload: AppToastPayload | null) {
  getListeners().forEach((fn) => fn(payload));
}

let seq = 0;

/**
 * 弹出一条 Toast。同一条消息在展示期间会被去重，避免连弹。
 */
export function showToast(
  message: string,
  options?: { duration?: number; variant?: 'default' | 'danger' | 'success' },
): void {
  const duration = options?.duration ?? 2000;
  const variant = options?.variant ?? 'default';

  const g = globalThis as typeof globalThis & {
    [CURRENT_KEY]?: { message: string; timer: ReturnType<typeof setTimeout> };
  };
  if (g[CURRENT_KEY]?.message === message) {
    return;
  }
  if (g[CURRENT_KEY]?.timer) {
    clearTimeout(g[CURRENT_KEY].timer);
  }

  const id = ++seq;
  const payload: AppToastPayload = { id, message, duration, variant };
  g[CURRENT_KEY] = {
    message,
    timer: setTimeout(() => {
      g[CURRENT_KEY] = undefined;
      emit(null);
    }, duration),
  };
  emit(payload);
}
