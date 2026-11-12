import { getAgentIdFromAuth } from '@/core/auth';
import { getAgentId } from '@/core/im';

export type SiderActorBrand = {
  actorPlatformID: string;
  nickname: string;
  faceURL?: string;
};

type Listener = (actor: SiderActorBrand | null) => void;

const STORAGE_PREFIX = 'qh.siderActorBrand.';

let actor: SiderActorBrand | null = null;
const listeners = new Set<Listener>();

function notify(): void {
  for (const cb of listeners) {
    try {
      cb(actor);
    } catch {
      // ignore
    }
  }
}

function scopeId(): string {
  return getAgentId()?.trim() || getAgentIdFromAuth()?.trim() || '';
}

function storageKey(id: string): string {
  return `${STORAGE_PREFIX}${id}`;
}

function readStored(id: string): SiderActorBrand | null {
  if (typeof localStorage === 'undefined') return null;
  try {
    const raw = localStorage.getItem(storageKey(id));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<SiderActorBrand>;
    const actorPlatformID = parsed.actorPlatformID?.trim() ?? '';
    const nickname = parsed.nickname?.trim() ?? '';
    if (!actorPlatformID || !nickname) return null;
    const faceURL = parsed.faceURL?.trim();
    return { actorPlatformID, nickname, faceURL: faceURL || undefined };
  } catch {
    return null;
  }
}

function writeStored(id: string, next: SiderActorBrand | null): void {
  if (typeof localStorage === 'undefined') return;
  try {
    const key = storageKey(id);
    if (!next) {
      localStorage.removeItem(key);
      return;
    }
    localStorage.setItem(key, JSON.stringify(next));
  } catch {
    // ignore quota
  }
}

function sameBrand(a: SiderActorBrand | null, b: SiderActorBrand | null): boolean {
  return (
    a === b ||
    (a != null &&
      b != null &&
      a.actorPlatformID === b.actorPlatformID &&
      a.nickname === b.nickname &&
      (a.faceURL ?? '') === (b.faceURL ?? ''))
  );
}

export function getSiderActorBrand(): SiderActorBrand | null {
  return actor;
}

export function setSiderActorBrand(next: SiderActorBrand | null): void {
  if (sameBrand(actor, next)) return;
  actor = next;
  const id = scopeId();
  if (id) writeStored(id, next);
  notify();
}

/** 刷新 / 登录后恢复上次选中的接待者。 */
export function hydrateSiderActorBrand(): SiderActorBrand | null {
  const id = scopeId();
  if (!id) return actor;
  const stored = readStored(id);
  if (sameBrand(actor, stored)) return actor;
  actor = stored;
  notify();
  return actor;
}

export function subscribeSiderActorBrand(cb: Listener): () => void {
  listeners.add(cb);
  cb(actor);
  return () => {
    listeners.delete(cb);
  };
}
