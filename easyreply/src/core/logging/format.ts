import {
  LOG_ARRAY_MAX_ITEMS,
  LOG_PAYLOAD_MAX_CHARS,
  LOG_SANITIZE_MAX_DEPTH,
  LOG_VALUE_MAX_CHARS,
  type LogExportRange,
} from './types';

const SENSITIVE_KEY_RE =
  /^(authorization|auth|token|access_token|refresh_token|password|passwd|secret|api_key|apikey)$/i;

/**
 * 媒体 / 二进制向字段：只留摘要。
 * 注意：不含普通 IM 文本 content（否则短聊天气泡也会被收成 [media-text]）
 */
const MEDIA_KEY_RE =
  /^(sourceUrl|videoUrl|snapshotUrl|imageUrl|fileUrl|url|objectKey|thumbnail|thumbUrl|faceURL|avatar|data|bigPicture|snapshotPicture)$/i;

const DATA_URL_RE = /^data:([a-z0-9.+/-]+)?;base64,/i;
const BASE64ISH_RE = /^[A-Za-z0-9+/=\s]{200,}$/;
const URL_RE = /^https?:\/\/\S+/i;

/** 本地时区：YYYY-MM-dd HH:mm:ss */
export function formatLogTimestamp(date = new Date()): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  const hh = String(date.getHours()).padStart(2, '0');
  const mm = String(date.getMinutes()).padStart(2, '0');
  const ss = String(date.getSeconds()).padStart(2, '0');
  return `${y}-${m}-${d} ${hh}:${mm}:${ss}`;
}

/** 文件名用日期：YYYY-MM-DD（兼容旧版按天文件） */
export function formatLogDateKey(date = new Date()): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

/** 文件名用小时段：YYYY-MM-DD_HH（本地时区，每小时一个文件） */
export function formatLogHourKey(date = new Date()): string {
  const day = formatLogDateKey(date);
  const hh = String(date.getHours()).padStart(2, '0');
  return `${day}_${hh}`;
}

export function parseLogDateKey(key: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(key);
  if (!m) return null;
  const dt = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return Number.isNaN(dt.getTime()) ? null : dt;
}

/** 解析文件 period 键：支持 YYYY-MM-DD_HH 与旧版 YYYY-MM-DD */
export function parseLogPeriodKey(key: string): Date | null {
  const hourly = /^(\d{4})-(\d{2})-(\d{2})_(\d{2})$/.exec(key);
  if (hourly) {
    const dt = new Date(
      Number(hourly[1]),
      Number(hourly[2]) - 1,
      Number(hourly[3]),
      Number(hourly[4]),
      0,
      0,
      0,
    );
    return Number.isNaN(dt.getTime()) ? null : dt;
  }
  return parseLogDateKey(key);
}

/** 该 period 文件覆盖的半开区间 [start, end) */
export function logPeriodBounds(periodKey: string): { start: Date; end: Date } | null {
  const start = parseLogPeriodKey(periodKey);
  if (!start) return null;
  const end = new Date(start);
  if (/_\d{2}$/.test(periodKey)) end.setHours(end.getHours() + 1);
  else end.setDate(end.getDate() + 1);
  return { start, end };
}

/** 保留含今天共 retentionDays 天内的 period 键（按文件起始时刻判断） */
export function isWithinRetention(periodKey: string, retentionDays: number, now = new Date()): boolean {
  const dt = parseLogPeriodKey(periodKey);
  if (!dt) return false;
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const oldest = new Date(start);
  oldest.setDate(oldest.getDate() - (retentionDays - 1));
  return dt >= oldest;
}

/** 文件是否落在导出时间范围内（按小时/天文件覆盖区间与窗口是否相交） */
export function isWithinExportRange(
  periodKey: string,
  range: LogExportRange,
  now = new Date(),
): boolean {
  if (range === 'all') return true;
  const bounds = logPeriodBounds(periodKey);
  if (!bounds) return false;
  const { start, end } = bounds;
  if (range === 'today') {
    const dayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const dayEnd = new Date(dayStart);
    dayEnd.setDate(dayEnd.getDate() + 1);
    return start < dayEnd && end > dayStart;
  }
  const from = new Date(now.getTime() - 3 * 60 * 60 * 1000);
  return start <= now && end > from;
}

function truncate(text: string, max = LOG_VALUE_MAX_CHARS): string {
  if (!Number.isFinite(max) || text.length <= max) return text;
  return `${text.slice(0, max)}…[truncated ${text.length - max} chars]`;
}

function shortHash(text: string): string {
  let h = 0;
  for (let i = 0; i < text.length; i += 1) {
    h = (h * 31 + text.charCodeAt(i)) | 0;
  }
  return (h >>> 0).toString(16).padStart(8, '0');
}

function summarizeUrl(url: string): string {
  try {
    const u = new URL(url);
    const path = u.pathname.length > 48 ? `${u.pathname.slice(0, 24)}…${u.pathname.slice(-16)}` : u.pathname;
    return `[url ${u.host}${path} len=${url.length}]`;
  } catch {
    return `[url len=${url.length} hash=${shortHash(url)}]`;
  }
}

/** 长字符串 / data-url / base64 / http(s) 媒体链只留摘要 */
export function summarizeLogString(text: string, opts?: { forceMedia?: boolean }): string {
  const s = text;
  if (!s) return s;

  const dataUrl = DATA_URL_RE.exec(s);
  if (dataUrl) {
    const mime = dataUrl[1] || 'unknown';
    return `[data-url ${mime} len=${s.length} hash=${shortHash(s)}]`;
  }

  if (URL_RE.test(s) && (opts?.forceMedia || s.length > 120 || /\/(edge\/)?(image|file|video|voice|oss)\b/i.test(s))) {
    return summarizeUrl(s);
  }

  if (opts?.forceMedia && s.length > 80) {
    return `[media-text len=${s.length} hash=${shortHash(s)}]`;
  }

  if (s.length >= 200 && BASE64ISH_RE.test(s.replace(/\s/g, ''))) {
    return `[base64 len=${s.length} hash=${shortHash(s)}]`;
  }

  // 普通业务文本 / JSON 字符串：完整保留，供导出诊断日志排查
  return s;
}

function summarizeContentField(text: string): string {
  const s = text;
  if (!s) return s;
  if (DATA_URL_RE.test(s) || (s.length >= 200 && BASE64ISH_RE.test(s.replace(/\s/g, '')))) {
    return summarizeLogString(s, { forceMedia: true });
  }
  if (s.length > 120 && (s.includes('"sourceUrl"') || s.includes('"videoUrl"') || s.includes('edge/image'))) {
    return summarizeLogString(s, { forceMedia: true });
  }
  return s;
}

export function sanitizeForLog(value: unknown, depth = 0, keyHint?: string): unknown {
  if (value == null) return value;
  if (typeof value === 'string') {
    if (keyHint === 'content') return summarizeContentField(value);
    const forceMedia = !!keyHint && MEDIA_KEY_RE.test(keyHint);
    return summarizeLogString(value, { forceMedia });
  }
  if (typeof value === 'number' || typeof value === 'boolean') return value;
  if (depth >= LOG_SANITIZE_MAX_DEPTH) return '[MaxDepth]';
  if (Array.isArray(value)) {
    if (value.length > LOG_ARRAY_MAX_ITEMS) {
      return [
        ...value.slice(0, LOG_ARRAY_MAX_ITEMS).map((v) => sanitizeForLog(v, depth + 1, keyHint)),
        `…(+${value.length - LOG_ARRAY_MAX_ITEMS})`,
      ];
    }
    return value.map((v) => sanitizeForLog(v, depth + 1, keyHint));
  }
  if (typeof value === 'object') {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      out[k] = SENSITIVE_KEY_RE.test(k) ? '***' : sanitizeForLog(v, depth + 1, k);
    }
    return out;
  }
  return summarizeLogString(String(value));
}

/** sanitize 后的 JSON；默认整包上限 LOG_PAYLOAD_MAX_CHARS，避免业务帧被砍成 1.5KB */
export function safeJson(value: unknown, maxChars: number = LOG_PAYLOAD_MAX_CHARS): string {
  try {
    return truncate(JSON.stringify(sanitizeForLog(value)) ?? 'null', maxChars);
  } catch {
    return truncate(String(value), maxChars);
  }
}

/** 一条日志文本（不含末尾空行） */
export function buildLogLine(body: string, at = new Date()): string {
  const text = body.replace(/\r\n/g, '\n').trimEnd();
  return `${formatLogTimestamp(at)} ${text}`;
}

/** 写入文件时：行 + 空一行 */
export function buildLogRecord(body: string, at = new Date()): string {
  return `${buildLogLine(body, at)}\n\n`;
}
