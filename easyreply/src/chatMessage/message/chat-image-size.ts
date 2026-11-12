// ============================================================
// 聊天图片气泡展示尺寸（类微信：等比缩放 + 长边/短边限制）
// ============================================================

/** 长边上限（dp） */
const MAX_LONG = 240;
/** 表情包长边上限（更小） */
const EMOJI_MAX_LONG = 96;
/** 常规图短边下限 */
const MIN_SHORT = 80;
/** 细长图（长宽比 > 2.5）短边下限 */
const MIN_SHORT_STRIP = 40;
/** 无元数据时的默认边长 */
const FALLBACK = 160;
const EMOJI_FALLBACK = 80;

export type ChatImageSizeVariant = 'image' | 'emoji';

/**
 * 根据原图宽高计算聊天气泡内展示尺寸。
 * - 长边不超过 MAX_LONG（emoji 用 EMOJI_MAX_LONG）
 * - 短边不低于 MIN_SHORT（emoji 不强制放大）
 * - 消息元数据可作占位；调用方应以 loadAsync / onLoad 实测尺寸再计算
 */
export function computeChatImageDisplaySize(
  rawWidth?: number,
  rawHeight?: number,
  variant: ChatImageSizeVariant = 'image',
): { width: number; height: number } {
  const isEmoji = variant === 'emoji';
  const maxLong = isEmoji ? EMOJI_MAX_LONG : MAX_LONG;
  const fallback = isEmoji ? EMOJI_FALLBACK : FALLBACK;

  const w = Number(rawWidth);
  const h = Number(rawHeight);
  if (!Number.isFinite(w) || !Number.isFinite(h) || w <= 0 || h <= 0) {
    return { width: fallback, height: fallback };
  }

  let width = w;
  let height = h;

  const scaleDownIfNeeded = () => {
    const long = Math.max(width, height);
    if (long > maxLong) {
      const scale = maxLong / long;
      width *= scale;
      height *= scale;
    }
  };

  scaleDownIfNeeded();

  if (!isEmoji) {
    const long = Math.max(width, height);
    const short = Math.min(width, height);
    const minShort = long / short > 2.5 ? MIN_SHORT_STRIP : MIN_SHORT;

    if (short < minShort) {
      const scale = minShort / short;
      width *= scale;
      height *= scale;
      scaleDownIfNeeded();
    }
  }

  return { width: Math.round(width), height: Math.round(height) };
}

/** content 内 picture.type === 'emoji' */
export function isEmojiPictureType(type?: string): boolean {
  return (type ?? '').trim().toLowerCase() === 'emoji';
}

/** 从 Image onLoad 事件读取真实宽高（兼容 expo-image / RN / Web） */
export function readImageLoadDimensions(event: unknown): { width?: number; height?: number } {
  const expo = event as { source?: { width?: number; height?: number } };
  if (expo?.source?.width && expo.source.height && expo.source.width > 0 && expo.source.height > 0) {
    return { width: expo.source.width, height: expo.source.height };
  }

  const ne = (event as { nativeEvent?: Record<string, unknown> })?.nativeEvent;
  if (!ne) return {};

  const source = ne.source as { width?: number; height?: number } | undefined;
  if (source?.width && source?.height && source.width > 0 && source.height > 0) {
    return { width: source.width, height: source.height };
  }

  const nw = ne.width as number | undefined;
  const nh = ne.height as number | undefined;
  if (nw && nh && nw > 0 && nh > 0) {
    return { width: nw, height: nh };
  }

  const target = ne.target as
    | { naturalWidth?: number; naturalHeight?: number; width?: number; height?: number }
    | undefined;
  const tw = target?.naturalWidth ?? target?.width;
  const th = target?.naturalHeight ?? target?.height;
  if (tw && th && tw > 0 && th > 0) {
    return { width: tw, height: th };
  }

  return {};
}
