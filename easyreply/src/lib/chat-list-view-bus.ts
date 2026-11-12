export type ChatListView = 'chat' | 'hosts';

type Listener = (view: ChatListView) => void;

let view: ChatListView = 'chat';
const listeners = new Set<Listener>();

function notify(): void {
  for (const cb of listeners) {
    try {
      cb(view);
    } catch {
      // ignore
    }
  }
}

export function getChatListView(): ChatListView {
  return view;
}

export function setChatListView(next: ChatListView): void {
  if (view === next) return;
  view = next;
  notify();
}

export function subscribeChatListView(cb: Listener): () => void {
  listeners.add(cb);
  cb(view);
  return () => {
    listeners.delete(cb);
  };
}
