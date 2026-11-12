export type ProfileModalView = 'profile' | 'reset-password';

type Listener = (view: ProfileModalView | null) => void;

let view: ProfileModalView | null = null;
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

export function getProfileModalView(): ProfileModalView | null {
  return view;
}

export function openProfileModal(next: ProfileModalView = 'profile'): void {
  view = next;
  notify();
}

export function closeProfileModal(): void {
  view = null;
  notify();
}

export function closeResetPasswordModal(): void {
  view = view === 'reset-password' ? 'profile' : null;
  notify();
}

export function subscribeProfileModal(cb: Listener): () => void {
  listeners.add(cb);
  cb(view);
  return () => {
    listeners.delete(cb);
  };
}
