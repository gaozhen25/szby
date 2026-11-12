import type { LogChannel } from './types';

export type LogStoreFileInfo = {
  name: string;
  uri: string;
  /** 文件 period 键：YYYY-MM-DD_HH；旧版按天文件为 YYYY-MM-DD */
  dateKey: string;
  channel: LogChannel;
  size: number;
};

export type LogStore = {
  ensureReady: () => Promise<void>;
  /** periodKey 通常为 formatLogHourKey() 的返回值 */
  append: (channel: LogChannel, periodKey: string, chunk: string) => Promise<void>;
  listFiles: () => Promise<LogStoreFileInfo[]>;
  readFile: (uri: string) => Promise<string>;
  deleteFile: (uri: string) => Promise<void>;
  /** 导出临时文件；Web 可返回空字符串表示走 Blob 下载 */
  writeTempExportFile: (fileName: string, content: string | Uint8Array) => Promise<string>;
};

export function parseLogFileName(name: string): { dateKey: string; channel: LogChannel } | null {
  // 新版：YYYY-MM-DD_HH_{channel}.txt
  const hourly = /^(\d{4}-\d{2}-\d{2}_\d{2})_(ws|http|app)\.txt$/.exec(name);
  if (hourly) return { dateKey: hourly[1], channel: hourly[2] as LogChannel };
  // 旧版：YYYY-MM-DD_{channel}.log|txt
  const daily = /^(\d{4}-\d{2}-\d{2})_(ws|http|app)\.(?:log|txt)$/.exec(name);
  if (daily) return { dateKey: daily[1], channel: daily[2] as LogChannel };
  return null;
}

export function logFileName(periodKey: string, channel: LogChannel): string {
  return `${periodKey}_${channel}.txt`;
}
