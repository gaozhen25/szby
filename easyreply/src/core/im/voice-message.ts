/** contentType=103 语音消息 content（与下行 voice 结构对齐） */
export type VoiceMessageContent = {
  dataSize: number;
  /** 时长，毫秒 */
  duration: number;
  sourceUrl: string;
  uuid: string;
};

function newUUID(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

/** 构造 contentType=103 的语音消息 content（先上传音频，再带 sourceUrl 发送） */
export function buildVoiceMessageContent(params: {
  sourceUrl: string;
  objectKey?: string;
  dataSize: number;
  /** 时长（秒），会转为毫秒写入 content */
  durationSec: number;
  uuid?: string;
}): VoiceMessageContent {
  return {
    dataSize: params.dataSize,
    duration: Math.max(1, Math.round(params.durationSec * 1000)),
    sourceUrl: params.objectKey || params.sourceUrl,
    uuid: params.uuid || newUUID(),
  };
}

/**
 * 将下行 duration 规范为秒。
 * 兼容秒（如 2）与毫秒（如 2000）。
 */
export function normalizeVoiceDurationSec(raw: unknown): number {
  const d = Number(raw);
  if (!Number.isFinite(d) || d <= 0) return 1;
  if (d >= 1000) return Math.max(1, Math.round(d / 1000));
  return Math.max(1, Math.round(d));
}
