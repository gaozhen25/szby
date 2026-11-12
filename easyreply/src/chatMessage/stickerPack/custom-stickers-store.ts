// ============================================================
// 自定义表情（单个表情）本地缓存
// - 仅存 URL 等元数据，按账号隔离
// - 打开表情包面板 / 管理页时再加载
// ============================================================
import AsyncStorage from '@react-native-async-storage/async-storage';
import { Image as ExpoImage } from 'expo-image';
import { Platform } from 'react-native';
import { getAgentAccount, getAgentIdFromAuth } from '@/core/auth';

export type CustomSticker = {
  id: string;
  url: string;
  objectKey?: string;
  width?: number;
  height?: number;
  createdAt: number;
};

const KEY_PREFIX = 'custom_stickers_v1:';
export const MAX_CUSTOM_STICKERS = 100;
const MAX_STICKERS = MAX_CUSTOM_STICKERS;
/** 服务端要求 picture.width/height；探测失败时兜底 */
const DEFAULT_STICKER_SIZE = 300;

type Listener = (list: CustomSticker[]) => void;

let scopeKey: string | null = null;
let list: CustomSticker[] = [];
let hydrated = false;
let hydrating: Promise<void> | null = null;
const listeners = new Set<Listener>();

function resolveScopeKey(): string | null {
  const account = getAgentAccount()?.trim();
  if (account) return `account:${account}`;
  const agentId = getAgentIdFromAuth()?.trim();
  if (agentId) return `agent:${agentId}`;
  return null;
}

function storageKey(scope: string): string {
  return `${KEY_PREFIX}${scope}`;
}

/** 绝对 OSS URL → edge/... 或 stickers/... objectKey；已是相对路径则原样返回 */
export function inferStickerObjectKey(url: string): string | undefined {
  const raw = url.trim();
  if (!raw) return undefined;
  const isImKey = (key: string) => key.startsWith('edge/') || key.startsWith('stickers/');
  if (!/^https?:\/\//i.test(raw)) {
    const key = raw.replace(/^\//, '');
    return isImKey(key) ? key : undefined;
  }
  try {
    const path = new URL(raw).pathname.replace(/^\//, '');
    return isImKey(path) ? path : undefined;
  } catch {
    return undefined;
  }
}

export async function resolveStickerDimensions(params: {
  url: string;
  width?: number;
  height?: number;
}): Promise<{ width: number; height: number }> {
  const w = params.width && params.width > 0 ? params.width : 0;
  const h = params.height && params.height > 0 ? params.height : 0;
  if (w > 0 && h > 0) return { width: w, height: h };

  const url = params.url.trim();
  // Web 上跨域 OSS 图用 loadAsync（内部 fetch）常被 CORS 拦下，控制台报红但发送仍会成功；
  // 有尺寸时已提前返回；无尺寸时直接用兜底，避免无意义失败请求。
  if (!url || (Platform.OS === 'web' && /^https?:\/\//i.test(url))) {
    return { width: DEFAULT_STICKER_SIZE, height: DEFAULT_STICKER_SIZE };
  }

  try {
    const ref = await ExpoImage.loadAsync(url);
    if (ref.width > 0 && ref.height > 0) {
      return { width: ref.width, height: ref.height };
    }
  } catch {
    // ignore
  }
  return { width: DEFAULT_STICKER_SIZE, height: DEFAULT_STICKER_SIZE };
}

function notify(): void {
  const snap = [...list];
  for (const cb of listeners) {
    try {
      cb(snap);
    } catch {
      // ignore subscriber errors
    }
  }
}

async function persist(): Promise<void> {
  if (!scopeKey) return;
  try {
    await AsyncStorage.setItem(storageKey(scopeKey), JSON.stringify(list));
  } catch (e) {
    console.warn('[CustomStickers] 写入本地缓存失败', e);
  }
}

function normalizeList(raw: unknown): CustomSticker[] {
  if (!Array.isArray(raw)) return [];
  const out: CustomSticker[] = [];
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue;
    const o = item as Partial<CustomSticker>;
    const id = typeof o.id === 'string' ? o.id.trim() : '';
    const url = typeof o.url === 'string' ? o.url.trim() : '';
    if (!id || !url) continue;
    out.push({
      id,
      url,
      objectKey: typeof o.objectKey === 'string' ? o.objectKey : undefined,
      width: typeof o.width === 'number' && o.width > 0 ? o.width : undefined,
      height: typeof o.height === 'number' && o.height > 0 ? o.height : undefined,
      createdAt: typeof o.createdAt === 'number' ? o.createdAt : Date.now(),
    });
  }
  return out;
}

/** 打开面板/管理页时调用：按当前账号 hydrate */
export async function ensureCustomStickersHydrated(): Promise<CustomSticker[]> {
  const nextScope = resolveScopeKey();
  if (!nextScope) {
    scopeKey = null;
    list = [];
    hydrated = true;
    notify();
    return [];
  }

  if (hydrated && scopeKey === nextScope) return [...list];
  if (hydrating && scopeKey === nextScope) {
    await hydrating;
    return [...list];
  }

  scopeKey = nextScope;
  hydrated = false;
  hydrating = (async () => {
    try {
      const raw = await AsyncStorage.getItem(storageKey(nextScope));
      list = raw ? normalizeList(JSON.parse(raw)) : [];
    } catch (e) {
      console.warn('[CustomStickers] 读取本地缓存失败', e);
      list = [];
    } finally {
      hydrated = true;
      hydrating = null;
      notify();
    }
  })();

  await hydrating;
  return [...list];
}

export function getCustomStickersSnapshot(): CustomSticker[] {
  return [...list];
}

export function subscribeCustomStickers(cb: Listener): () => void {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}

export async function addCustomSticker(params: {
  url: string;
  objectKey?: string;
  width?: number;
  height?: number;
}): Promise<CustomSticker> {
  await ensureCustomStickersHydrated();
  const url = params.url.trim();
  if (!url) throw new Error('表情地址无效');

  const objectKey =
    params.objectKey?.trim() || inferStickerObjectKey(url) || undefined;
  const already = list.some((s) => {
    if (s.url === url) return true;
    if (objectKey && (s.objectKey === objectKey || inferStickerObjectKey(s.url) === objectKey)) {
      return true;
    }
    return false;
  });
  if (already) throw new Error('该表情已添加');
  if (list.length >= MAX_STICKERS) {
    throw new Error(`最多添加 ${MAX_STICKERS} 个自定义表情`);
  }

  const dims = await resolveStickerDimensions({
    url,
    width: params.width,
    height: params.height,
  });

  const sticker: CustomSticker = {
    id: `sticker-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    url,
    objectKey,
    width: dims.width,
    height: dims.height,
    createdAt: Date.now(),
  };
  list = [sticker, ...list];
  notify();
  await persist();
  return sticker;
}

/** 发送前补齐宽高；已缓存表情缺尺寸时写回本地 */
export async function ensureCustomStickerSendMeta(
  sticker: CustomSticker,
): Promise<CustomSticker> {
  await ensureCustomStickersHydrated();
  const dims = await resolveStickerDimensions({
    url: sticker.url,
    width: sticker.width,
    height: sticker.height,
  });
  const objectKey =
    sticker.objectKey?.trim() || inferStickerObjectKey(sticker.url) || undefined;
  const next: CustomSticker = {
    ...sticker,
    width: dims.width,
    height: dims.height,
    objectKey,
  };
  const idx = list.findIndex((s) => s.id === sticker.id);
  if (
    idx >= 0 &&
    (list[idx].width !== next.width ||
      list[idx].height !== next.height ||
      list[idx].objectKey !== next.objectKey)
  ) {
    list = list.map((s, i) => (i === idx ? next : s));
    notify();
    await persist();
  }
  return next;
}

export async function removeCustomStickers(ids: string[]): Promise<number> {
  await ensureCustomStickersHydrated();
  const idSet = new Set(ids.map((id) => id.trim()).filter(Boolean));
  if (idSet.size === 0) return 0;
  const before = list.length;
  list = list.filter((s) => !idSet.has(s.id));
  const removed = before - list.length;
  if (removed > 0) {
    notify();
    await persist();
  }
  return removed;
}

/** 将选中项移动到列表最前（管理页「移动」） */
export async function moveCustomStickersToFront(ids: string[]): Promise<void> {
  await ensureCustomStickersHydrated();
  const idSet = new Set(ids.map((id) => id.trim()).filter(Boolean));
  if (idSet.size === 0) return;
  const selected = list.filter((s) => idSet.has(s.id));
  if (selected.length === 0) return;
  const rest = list.filter((s) => !idSet.has(s.id));
  list = [...selected, ...rest];
  notify();
  await persist();
}
