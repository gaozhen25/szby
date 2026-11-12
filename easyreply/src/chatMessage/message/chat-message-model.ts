import {
  isOutgoingServerMessage,
  normalizeSendTimeMs,
  parseApiMessageContent,
} from '@/core/im';
import type { IMServerMessage } from '@/core/im';
import { isEmojiPictureType } from '@/chatMessage/message/chat-image-size';
import { normalizeVoiceDurationSec } from '@/core/im/voice-message';
import { normalizeVideoDurationSec } from '@/core/im/video-message';
import {
  formatLocationPreview,
  parseLocationMessageContent,
} from '@/core/im/location-message';
import {
  extractDisplayQuote,
  type DisplayQuote,
} from '@/core/im/quote-message';

export type { DisplayQuote };

// 统一展示用消息体
export type DisplayMessageBase = {
  key: string;            // 渲染 key（serverMsgID 或本地临时 id）
  serverMsgID?: string;   // 服务端消息id（去重）
  /** 本地发出时的临时 id：key 升成 serverMsgID 后仍用于 submit_result 配对 */
  clientMsgID?: string;
  mine: boolean;          // 是否我方（agent）发出
  time: number;           // sendTime(ms)
  status?: 'sending' | 'sent' | 'failed'; // 本地发送态
  /** contentType=114：被引用的原消息，展示在气泡下方 */
  quote?: DisplayQuote;
};
export type DisplayTextMessage = DisplayMessageBase & { kind: 'text'; text: string };
export type DisplayImageMessage = DisplayMessageBase & {
  kind: 'image';
  imageUrl: string;
  imageWidth?: number;
  imageHeight?: number;
  /** bigPicture/snapshotPicture.type === 'emoji' */
  isEmojiSticker?: boolean;
};
export type DisplayVoiceMessage = DisplayMessageBase & {
  kind: 'voice';
  /** 可播放的绝对/相对 url */
  voiceUrl: string;
  /** 时长（秒） */
  duration: number;
};
export type DisplayFileMessage = DisplayMessageBase & {
  kind: 'file';
  fileName: string;
  fileSize: number;
  fileUrl: string;
};
export type DisplayVideoMessage = DisplayMessageBase & {
  kind: 'video';
  videoUrl: string;
  snapshotUrl: string;
  snapshotWidth?: number;
  snapshotHeight?: number;
  /** 时长（秒） */
  duration: number;
};
export type DisplayLocationMessage = DisplayMessageBase & {
  kind: 'location';
  description: string;
  latitude: number;
  longitude: number;
};
export type DisplayMessage =
  | DisplayTextMessage
  | DisplayImageMessage
  | DisplayVoiceMessage
  | DisplayFileMessage
  | DisplayVideoMessage
  | DisplayLocationMessage;


/** 微信风格：与上一条间隔超过此时长才插入时间格（5 分钟） */
const TIME_CELL_GAP_MS = 5 * 60 * 1000;

export type ChatListItem =
  | { type: 'time'; key: string; time: number }
  | { type: 'message'; key: string; message: DisplayMessage };

/** 在消息列表中按间隔插入独立 Timecell（不挂在气泡下） */
export function buildChatListItems(messages: DisplayMessage[]): ChatListItem[] {
  const items: ChatListItem[] = [];
  const seenKeys = new Set<string>();
  let prevMsgTime = 0;
  for (const msg of messages) {
    if (!msg.key || seenKeys.has(msg.key)) continue;
    seenKeys.add(msg.key);
    const t = msg.time || 0;
    if (!prevMsgTime || Math.abs(t - prevMsgTime) >= TIME_CELL_GAP_MS) {
      items.push({ type: 'time', key: `time-${msg.key}`, time: t });
    }
    prevMsgTime = t;
    items.push({ type: 'message', key: msg.key, message: msg });
  }
  return items;
}

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

export function toDisplay(msg: IMServerMessage, actorPlatformID: string): DisplayMessage {
  const mine = isOutgoingServerMessage(msg, actorPlatformID);
  const time = normalizeSendTimeMs(msg.sendTime);
  const quote = extractDisplayQuote(msg.content);
  const finish = (display: DisplayMessage): DisplayMessage =>
    quote && !display.quote ? { ...display, quote } : display;

  // 语音：contentType=103，content 为 { dataSize, duration(ms), sourceUrl, uuid }
  if (msg.contentType === 103) {
    let voiceUrl = '';
    let duration = 1;
    try {
      const parsed = typeof msg.content === 'string' ? JSON.parse(msg.content) : msg.content;
      const rawUrl =
        (typeof parsed?.sourceUrl === 'string' && parsed.sourceUrl) ||
        (typeof parsed?.url === 'string' && parsed.url) ||
        '';
      voiceUrl = resolveMediaUrl(rawUrl);
      duration = normalizeVoiceDurationSec(parsed?.duration);
    } catch {
      voiceUrl = '';
    }
    return finish({
      key: msg.serverMsgID,
      serverMsgID: msg.serverMsgID,
      mine,
      kind: 'voice',
      voiceUrl,
      duration,
      time,
      status: 'sent',
    });
  }

  // 视频：contentType=104，content 为 { duration, snapshot*, videoUrl, videoType, ... }
  if (msg.contentType === 104) {
    let videoUrl = '';
    let snapshotUrl = '';
    let snapshotWidth: number | undefined;
    let snapshotHeight: number | undefined;
    let duration = 1;
    try {
      const parsed = typeof msg.content === 'string' ? JSON.parse(msg.content) : msg.content;
      const rawVideo =
        (typeof parsed?.videoUrl === 'string' && parsed.videoUrl) ||
        (typeof parsed?.sourceUrl === 'string' && parsed.sourceUrl) ||
        '';
      const rawSnap =
        (typeof parsed?.snapshotUrl === 'string' && parsed.snapshotUrl) ||
        '';
      videoUrl = resolveMediaUrl(rawVideo);
      snapshotUrl = resolveMediaUrl(rawSnap);
      const w = Number(parsed?.snapshotWidth);
      const h = Number(parsed?.snapshotHeight);
      if (Number.isFinite(w) && w > 0) snapshotWidth = w;
      if (Number.isFinite(h) && h > 0) snapshotHeight = h;
      duration = normalizeVideoDurationSec(parsed?.duration);
    } catch {
      videoUrl = '';
    }
    return finish({
      key: msg.serverMsgID,
      serverMsgID: msg.serverMsgID,
      mine,
      kind: 'video',
      videoUrl,
      snapshotUrl,
      snapshotWidth,
      snapshotHeight,
      duration,
      time,
      status: 'sent',
    });
  }

  // 文件：contentType=105，content 为 { fileName, fileSize, sourceUrl, uuid }
  if (msg.contentType === 105) {
    let fileName = '文件';
    let fileSize = 0;
    let fileUrl = '';
    try {
      const parsed = typeof msg.content === 'string' ? JSON.parse(msg.content) : msg.content;
      if (typeof parsed?.fileName === 'string' && parsed.fileName.trim()) {
        fileName = parsed.fileName.trim();
      }
      const size = Number(parsed?.fileSize);
      if (Number.isFinite(size) && size >= 0) fileSize = size;
      const rawUrl =
        (typeof parsed?.sourceUrl === 'string' && parsed.sourceUrl) ||
        (typeof parsed?.url === 'string' && parsed.url) ||
        '';
      fileUrl = resolveMediaUrl(rawUrl);
    } catch {
      fileUrl = '';
    }
    return finish({
      key: msg.serverMsgID,
      serverMsgID: msg.serverMsgID,
      mine,
      kind: 'file',
      fileName,
      fileSize,
      fileUrl,
      time,
      status: 'sent',
    });
  }

  // 位置：contentType=109，content 为 { description, latitude, longitude }
  if (msg.contentType === 109) {
    const loc = parseLocationMessageContent(msg.content);
    return finish({
      key: msg.serverMsgID,
      serverMsgID: msg.serverMsgID,
      clientMsgID: msg.clientMsgID,
      mine,
      kind: 'location',
      description: loc?.description || '',
      latitude: loc?.latitude ?? Number.NaN,
      longitude: loc?.longitude ?? Number.NaN,
      time,
      status: 'sent',
    });
  }

  // 图片/表情：contentType=102，content 为 JSON 字符串
  if (msg.contentType === 102) {
    let imageUrl = '';
    let imageWidth: number | undefined;
    let imageHeight: number | undefined;
    let isEmojiSticker = false;
    try {
      const parsed = typeof msg.content === 'string' ? JSON.parse(msg.content) : msg.content;
      const meta = pickPictureMeta(parsed);
      imageUrl = resolveMediaUrl(meta?.url || '');
      imageWidth = meta?.width;
      imageHeight = meta?.height;
      isEmojiSticker = isEmojiPictureType(meta?.type);
    } catch {
      imageUrl = '';
    }
    return finish({
      key: msg.serverMsgID,
      serverMsgID: msg.serverMsgID,
      mine,
      kind: 'image',
      imageUrl,
      imageWidth,
      imageHeight,
      isEmojiSticker,
      time,
      status: 'sent',
    });
  }
  return finish({
    key: msg.serverMsgID,
    serverMsgID: msg.serverMsgID,
    mine,
    kind: 'text',
    text: parseApiMessageContent(msg.content),
    time,
    status: 'sent',
  });
}

/** 展示消息 → 会话列表末条（预览/排序只需类型、文本、方向、时间） */
export function displayToLastServerMessage(m: DisplayMessage): IMServerMessage {
  const contentType =
    m.kind === 'image'
      ? 102
      : m.kind === 'voice'
        ? 103
        : m.kind === 'video'
          ? 104
          : m.kind === 'file'
            ? 105
            : m.kind === 'location'
              ? 109
              : 101;
  return {
    serverMsgID: m.serverMsgID?.trim() || '',
    contentType,
    content:
      m.kind === 'text'
        ? m.text
        : m.kind === 'location'
          ? formatLocationPreview({
              description: m.description,
              latitude: m.latitude,
              longitude: m.longitude,
            })
          : '',
    sendTime: m.time,
    direction: m.mine ? 1 : 0,
  };
}

/** 列表末条签名：忽略 sending→sent，避免同一条消息重复回写 */
export function displayLastMessageSignature(m: DisplayMessage | undefined): string {
  if (!m) return '';
  const body =
    m.kind === 'text'
      ? m.text
      : m.kind === 'image'
        ? m.imageUrl
        : m.kind === 'file'
          ? `${m.fileName}:${m.fileSize}`
          : m.kind === 'video'
            ? m.videoUrl
            : m.kind === 'location'
              ? `${m.latitude},${m.longitude}:${m.description}`
              : m.voiceUrl;
  return `${m.serverMsgID || m.key}|${m.kind}|${body}|${m.time}|${m.mine ? 1 : 0}`;
}
