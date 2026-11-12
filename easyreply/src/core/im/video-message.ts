/** contentType=104 视频消息 content（与下行 video 结构对齐） */
export type VideoMessageContent = {
  duration: number;
  snapshotHeight: number;
  snapshotSize: number;
  snapshotUUID: string;
  snapshotUrl: string;
  snapshotWidth: number;
  videoSize: number;
  videoType: string;
  videoUUID: string;
  videoUrl: string;
};

function newUUID(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

/** 构造 contentType=104 的视频消息 content（先上传视频+封面，再发送） */
export function buildVideoMessageContent(params: {
  videoUrl: string;
  videoObjectKey?: string;
  videoSize: number;
  videoType?: string;
  videoUUID?: string;
  /** 时长（秒），会转为毫秒写入 content */
  durationSec: number;
  snapshotUrl: string;
  snapshotObjectKey?: string;
  snapshotWidth: number;
  snapshotHeight: number;
  snapshotSize: number;
  snapshotUUID?: string;
}): VideoMessageContent {
  return {
    duration: Math.max(1, Math.round(params.durationSec * 1000)),
    snapshotHeight: Math.max(1, Math.round(params.snapshotHeight)),
    snapshotSize: Math.max(0, Math.round(params.snapshotSize)),
    snapshotUUID: params.snapshotUUID || newUUID(),
    snapshotUrl: params.snapshotObjectKey || params.snapshotUrl,
    snapshotWidth: Math.max(1, Math.round(params.snapshotWidth)),
    videoSize: Math.max(0, Math.round(params.videoSize)),
    videoType: params.videoType || 'mp4',
    videoUUID: params.videoUUID || newUUID(),
    videoUrl: params.videoObjectKey || params.videoUrl,
  };
}

/**
 * 将下行 duration 规范为秒。
 * 兼容秒（如 6）与毫秒（如 6000）。
 */
export function normalizeVideoDurationSec(raw: unknown): number {
  const d = Number(raw);
  if (!Number.isFinite(d) || d <= 0) return 1;
  if (d >= 1000) return Math.max(1, Math.round(d / 1000));
  return Math.max(1, Math.round(d));
}

export function formatVideoDurationLabel(durationSec: number): string {
  const sec = Math.max(0, Math.round(durationSec));
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}
