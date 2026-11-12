// ============================================================
// 本地诊断日志（纯前端工具）
// - 三类：ws / http / app
// - 文件：YYYY-MM-DD_HH_{type}.txt ，每种类型每小时一份，最多保留 3 天
// - 行格式：YYYY-MM-dd HH:mm:ss … ，条与条之间空一行
// ============================================================

export type LogChannel = 'ws' | 'http' | 'app';

export const LOG_CHANNELS: LogChannel[] = ['ws', 'http', 'app'];

/** 保留自然日数（含今天） */
export const LOG_RETENTION_DAYS = 3;

/** 导出诊断日志的时间范围 */
export type LogExportRange = '3h' | 'today' | 'all';

export const LOG_EXPORT_RANGE_LABEL: Record<LogExportRange, string> = {
  '3h': '三小时内',
  today: '今天',
  all: '全部日志',
};

/** 单字段字符串：仅媒体/base64/超长 URL 做摘要，普通文本不再按字段截断 */
export const LOG_VALUE_MAX_CHARS = Number.POSITIVE_INFINITY;

/**
 * 整段 JSON（sanitize 之后）截断上限。
 * claimed/list 等接口出参可能较大，需足够大才能在导出诊断日志里打全。
 */
export const LOG_PAYLOAD_MAX_CHARS = 5_000_000;

/** 数组展开上限（超出仍保留前缀 + 省略计数） */
export const LOG_ARRAY_MAX_ITEMS = 5_000;

/** sanitize 递归深度上限 */
export const LOG_SANITIZE_MAX_DEPTH = 20;

export type HttpLogEntry = {
  method: string;
  /** 接口后缀（相对 path，不含 host） */
  path: string;
  status?: number;
  req?: unknown;
  res?: unknown;
  error?: string;
  durationMs?: number;
};
