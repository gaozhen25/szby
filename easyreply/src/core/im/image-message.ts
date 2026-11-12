export interface PictureInfo {
  url: string;
  width?: number;
  height?: number;
  type?: string;
}

export interface ImageMessageContent {
  sourcePicture: PictureInfo;
  bigPicture: PictureInfo;
  snapshotPicture: PictureInfo;
}

export type ParsedImageDisplay = {
  imageUrl: string;
  imageWidth?: number;
  imageHeight?: number;
  isEmojiSticker: boolean;
};

type PictureMeta = { url?: string; width?: number; height?: number; type?: string };

function pickPictureMeta(payload: any): PictureMeta | null {
  const snap: PictureMeta | undefined = payload?.snapshotPicture;
  const big: PictureMeta | undefined = payload?.bigPicture;
  const src: PictureMeta | undefined = payload?.sourcePicture;
  const candidates = [snap, big, src].filter(Boolean) as PictureMeta[];
  const withSize = candidates.find((p) => p.width && p.height && p.width > 0 && p.height > 0);
  const base = withSize ?? candidates[0] ?? null;
  if (!base) return null;
  const type = candidates.find((p) => p.type)?.type ?? base.type;
  return { ...base, type };
}

function resolveMediaUrl(url: string): string {
  if (!url) return '';
  if (/^https?:\/\//i.test(url)) return url;
  const base = (process.env.EXPO_PUBLIC_OSS_BASE_URL || '').replace(/\/+$/, '');
  if (!base) return url;
  return `${base}/${url.replace(/^\/+/, '')}`;
}

/** 是否为 contentType=102 图片/表情包 JSON 结构 */
export function looksLikeImageMessageContent(content: unknown): boolean {
  let parsed: any = content;
  if (typeof content === 'string') {
    const s = content.trim();
    if (!s.startsWith('{')) return false;
    try {
      parsed = JSON.parse(s);
    } catch {
      return false;
    }
  }
  if (!parsed || typeof parsed !== 'object') return false;
  return !!(parsed.sourcePicture || parsed.bigPicture || parsed.snapshotPicture);
}

/**
 * 解析 contentType=102（或同结构 JSON）为可展示的图片 URL。
 * 相对 object key 会拼 EXPO_PUBLIC_OSS_BASE_URL。
 */
export function parseImageMessageContent(content: unknown): ParsedImageDisplay | null {
  try {
    const parsed = typeof content === 'string' ? JSON.parse(content) : content;
    const meta = pickPictureMeta(parsed);
    const imageUrl = resolveMediaUrl(meta?.url || '');
    if (!imageUrl) return null;
    return {
      imageUrl,
      imageWidth: meta?.width,
      imageHeight: meta?.height,
      isEmojiSticker: (meta?.type ?? '').trim().toLowerCase() === 'emoji',
    };
  } catch {
    return null;
  }
}

/** 构造 contentType=102 的图片消息 content 对象 */
export function buildImageMessageContent(params: {
  url: string;
  objectKey?: string;
  width?: number;
  height?: number;
  contentType?: string;
}): ImageMessageContent {
  const displayUrl = toImPictureUrl(params.objectKey || params.url);
  const pic: PictureInfo = {
    url: displayUrl,
    width: params.width,
    height: params.height,
    type: params.contentType || 'image/jpeg',
  };
  return {
    sourcePicture: pic,
    bigPicture: pic,
    snapshotPicture: pic,
  };
}

/**
 * IM 图片 url 需为相对 object key（如 edge/image/...），不能是 https 绝对地址。
 * 绝对 OSS URL 取 pathname；已是相对路径则原样。
 */
export function toImPictureUrl(raw: string): string {
  const s = (raw || '').trim();
  if (!s) return s;
  if (!/^https?:\/\//i.test(s)) return s.replace(/^\//, '');
  try {
    return new URL(s).pathname.replace(/^\//, '');
  } catch {
    return s;
  }
}
