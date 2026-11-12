/**
 * 本地诊断日志工具（纯前端，不依赖后台 / Sentry）
 *
 * 三类文件：`YYYY-MM-DD_HH_{ws|http|app}.txt`，每种类型每小时一份，保留 3 天；
 * 每条以 `YYYY-MM-dd HH:mm:ss` 开头，条间空一行；
 * Web 全量存 IndexedDB（分块 append），Native 存本地文件；
 * 导出为 zip，内含各类型独立 txt（Web Blob 下载 / Native 系统分享）。
 */
export type { LogChannel, HttpLogEntry, LogExportRange } from './types';
export { LOG_CHANNELS, LOG_EXPORT_RANGE_LABEL, LOG_RETENTION_DAYS } from './types';
export {
  initLocalLogging,
  flushLocalLogs,
  logWs,
  logHttp,
  logApp,
  getLocalLogStats,
  clearLocalLogs,
  exportLocalLogs,
} from './local-logger';
export { installAppErrorLogging, logBoundaryError } from './install-app-error-logging';
export { initBootProfile, markBootPhase, measureBootPhase } from './boot-profile';
