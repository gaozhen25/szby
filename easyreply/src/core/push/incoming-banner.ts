// ============================================================
// 应用内新消息横幅（状态栏下方）
// listeners 挂 globalThis，避免分包导致「发/订」不是同一份 Set
// ============================================================

export type IncomingBannerPayload = {
  id: number;
  title: string;
  body: string;
  avatarUrl?: string;
  taskID?: string;
  duration: number;
};

type Listener = (payload: IncomingBannerPayload | null) => void;

const GLOBAL_KEY = '__qinghui_incoming_banner_listeners__';
const CURRENT_KEY = '__qinghui_incoming_banner_current__';

function getListeners(): Set<Listener> {
  const g = globalThis as typeof globalThis & { [GLOBAL_KEY]?: Set<Listener> };
  if (!g[GLOBAL_KEY]) g[GLOBAL_KEY] = new Set();
  return g[GLOBAL_KEY]!;
}

export function subscribeIncomingBanner(listener: Listener): () => void {
  const listeners = getListeners();
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function emit(payload: IncomingBannerPayload | null) {
  getListeners().forEach((fn) => fn(payload));
}

let seq = 0;

export function showIncomingBanner(params: {
  title: string;
  body: string;
  avatarUrl?: string;
  taskID?: string;
  duration?: number;
}): void {
  const duration = params.duration ?? 4200;
  const g = globalThis as typeof globalThis & {
    [CURRENT_KEY]?: { timer: ReturnType<typeof setTimeout> };
  };
  if (g[CURRENT_KEY]?.timer) clearTimeout(g[CURRENT_KEY].timer);

  const payload: IncomingBannerPayload = {
    id: ++seq,
    title: params.title.trim() || '新消息',
    body: params.body.trim() || '您有一条新消息',
    avatarUrl: params.avatarUrl?.trim() || undefined,
    taskID: params.taskID?.trim() || undefined,
    duration,
  };
  g[CURRENT_KEY] = {
    timer: setTimeout(() => {
      g[CURRENT_KEY] = undefined;
      emit(null);
    }, duration),
  };
  emit(payload);
}

export function dismissIncomingBanner(): void {
  const g = globalThis as typeof globalThis & {
    [CURRENT_KEY]?: { timer: ReturnType<typeof setTimeout> };
  };
  if (g[CURRENT_KEY]?.timer) clearTimeout(g[CURRENT_KEY].timer);
  g[CURRENT_KEY] = undefined;
  emit(null);
}
