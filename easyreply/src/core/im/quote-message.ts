import { parseApiMessageContent } from '@/core/im/utils';

/** contentType=114 引用/回复消息 */
export const IM_CONTENT_TYPE_QUOTE = 114;

export type DisplayQuote = {
  text: string;
};

function asObject(raw: unknown): Record<string, unknown> | null {
  if (raw == null) return null;
  if (typeof raw === 'string') {
    const trimmed = raw.trim();
    if (!trimmed.startsWith('{') || !trimmed.endsWith('}')) return null;
    try {
      const parsed = JSON.parse(trimmed) as unknown;
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
      return parsed as Record<string, unknown>;
    } catch {
      return null;
    }
  }
  if (typeof raw === 'object' && !Array.isArray(raw)) return raw as Record<string, unknown>;
  return null;
}

function previewFromQuotedType(type: number | undefined): string {
  if (type === 102) return '[图片]';
  if (type === 103) return '[语音]';
  if (type === 104) return '[视频]';
  if (type === 105) return '[文件]';
  if (type === 109) return '[位置]';
  return '';
}

function textFromQuoteMessage(quoteMessage: unknown, quoteMessageType?: number): string {
  if (typeof quoteMessage === 'string') {
    const text = parseApiMessageContent(quoteMessage).trim();
    if (text) return text;
  }
  const o = asObject(quoteMessage);
  if (o) {
    if (typeof o.text === 'string' && o.text.trim()) return o.text.trim();
    if (typeof o.content === 'string' && o.content.trim()) {
      const text = parseApiMessageContent(o.content).trim();
      if (text) return text;
    }
    if (o.bigPicture || o.snapshotPicture || o.sourcePicture) return '[图片]';
    if (o.videoUrl || o.videoType) return '[视频]';
    if (typeof o.fileName === 'string' && (o.fileSize != null || o.sourceUrl != null)) return '[文件]';
    if (o.sourceUrl != null || (o.dataSize != null && o.duration != null)) return '[语音]';
    if (o.latitude != null && o.longitude != null) return '[位置]';
  }
  return previewFromQuotedType(quoteMessageType);
}

/** 从 114 / 带 quoteMessage 的 content 提取引用展示文案 */
export function extractDisplayQuote(raw: unknown): DisplayQuote | undefined {
  const o = asObject(raw);
  if (!o || !('quoteMessage' in o || 'quoteMessageType' in o)) return undefined;
  const typeRaw = o.quoteMessageType;
  const type = typeof typeRaw === 'number' ? typeRaw : Number(typeRaw);
  const text = textFromQuoteMessage(
    o.quoteMessage,
    Number.isFinite(type) ? type : undefined,
  );
  if (!text) return undefined;
  return { text };
}

/** 悬停气泡展示引用正文：`发送人：内容` 只弹出内容，否则整段 */
export function quoteHoverBody(text: string): string {
  const trimmed = text.trim();
  const match = trimmed.match(/^(.{1,20}?)[：:]\s*(.+)$/);
  if (!match) return trimmed;
  return match[2].trim() || trimmed;
}
