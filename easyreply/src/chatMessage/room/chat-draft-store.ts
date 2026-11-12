// ============================================================
// 聊天草稿（按 roomKey 隔离）
//
// 草稿刻意不放在聊天页 state：几百条会话 + 数十条消息时，
// 每敲一个字符都会重渲染整棵聊天页子树（消息列表、更多菜单、各类 Modal）。
// 这里下沉成外部 store，只有真正显示草稿的 composer 订阅，页面本身不因输入重渲染。
// ============================================================
import { useCallback, useSyncExternalStore } from 'react';

type Listener = () => void;

const drafts = new Map<string, string>();
const listeners = new Map<string, Set<Listener>>();

function normalizeRoomKey(roomKey: string): string {
  return roomKey?.trim() ?? '';
}

export function getChatDraft(roomKey: string): string {
  return drafts.get(normalizeRoomKey(roomKey)) ?? '';
}

function emit(key: string): void {
  const set = listeners.get(key);
  if (!set) return;
  for (const cb of set) {
    try {
      cb();
    } catch {
      // 单个订阅者异常不影响其他订阅者
    }
  }
}

/** 与 setState 同签名：支持直接赋值或 updater */
export function setChatDraft(
  roomKey: string,
  next: string | ((prev: string) => string),
): void {
  const key = normalizeRoomKey(roomKey);
  if (!key) return;
  const prev = drafts.get(key) ?? '';
  const value = typeof next === 'function' ? next(prev) : next;
  if (value === prev) return;
  if (value) drafts.set(key, value);
  else drafts.delete(key);
  emit(key);
}

/** 退出房间时调用，语义与原来的页面级 useState 一致（不跨房保留草稿） */
export function clearChatDraft(roomKey: string): void {
  const key = normalizeRoomKey(roomKey);
  if (!key || !drafts.has(key)) return;
  drafts.delete(key);
  emit(key);
}

export function subscribeChatDraft(roomKey: string, cb: Listener): () => void {
  const key = normalizeRoomKey(roomKey);
  if (!key) return () => {};
  let set = listeners.get(key);
  if (!set) {
    set = new Set<Listener>();
    listeners.set(key, set);
  }
  set.add(cb);
  return () => {
    set.delete(cb);
    if (set.size === 0) listeners.delete(key);
  };
}

/** composer 内部订阅草稿；页面层不要调用，否则又会把输入变成整页重渲染 */
export function useChatDraft(roomKey: string): string {
  const subscribe = useCallback(
    (cb: Listener) => subscribeChatDraft(roomKey, cb),
    [roomKey],
  );
  const getSnapshot = useCallback(() => getChatDraft(roomKey), [roomKey]);
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}
