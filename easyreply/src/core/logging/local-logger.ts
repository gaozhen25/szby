import { Platform } from 'react-native';
import * as Sharing from 'expo-sharing';
import {
  buildLogRecord,
  formatLogHourKey,
  isWithinExportRange,
  isWithinRetention,
  safeJson,
} from './format';
import { logStore } from './log-store';
import {
  LOG_CHANNELS,
  LOG_EXPORT_RANGE_LABEL,
  LOG_RETENTION_DAYS,
  type HttpLogEntry,
  type LogChannel,
  type LogExportRange,
} from './types';

const FLUSH_INTERVAL_MS = 1200;
const FLUSH_BATCH_SIZE = 24;

const queues: Record<LogChannel, string[]> = {
  ws: [],
  http: [],
  app: [],
};

let flushTimer: ReturnType<typeof setTimeout> | null = null;
let flushing = false;
let readyPromise: Promise<void> | null = null;
let pruneDone = false;

function enqueue(channel: LogChannel, body: string): void {
  queues[channel].push(buildLogRecord(body));
  const pending =
    queues.ws.length + queues.http.length + queues.app.length;
  if (pending >= FLUSH_BATCH_SIZE) {
    void flushLocalLogs();
    return;
  }
  if (flushTimer == null) {
    flushTimer = setTimeout(() => {
      flushTimer = null;
      void flushLocalLogs();
    }, FLUSH_INTERVAL_MS);
  }
}

async function ensureReady(): Promise<void> {
  if (!readyPromise) {
    readyPromise = logStore.ensureReady().catch((e) => {
      readyPromise = null;
      console.warn('[LocalLog] ensureReady failed', e);
    });
  }
  await readyPromise;
}

async function pruneOldFiles(): Promise<void> {
  if (pruneDone) return;
  try {
    await ensureReady();
    const files = await logStore.listFiles();
    for (const f of files) {
      if (!isWithinRetention(f.dateKey, LOG_RETENTION_DAYS)) {
        await logStore.deleteFile(f.uri);
      }
    }
    pruneDone = true;
  } catch (e) {
    console.warn('[LocalLog] prune failed', e);
  }
}

/** 启动时调用：建目录 + 清过期 + 可挂全局错误 */
export function initLocalLogging(): void {
  void pruneOldFiles();
}

export async function flushLocalLogs(): Promise<void> {
  if (flushing) return;
  const hasPending = LOG_CHANNELS.some((c) => queues[c].length > 0);
  if (!hasPending) return;

  flushing = true;
  try {
    await ensureReady();
    if (!pruneDone) await pruneOldFiles();
    const periodKey = formatLogHourKey();
    for (const channel of LOG_CHANNELS) {
      const batch = queues[channel];
      if (batch.length === 0) continue;
      queues[channel] = [];
      await logStore.append(channel, periodKey, batch.join(''));
    }
  } catch (e) {
    console.warn('[LocalLog] flush failed', e);
  } finally {
    flushing = false;
  }
}

function trailSentryApp(message: string, data?: Record<string, unknown>): void {
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { captureDiagLog } = require('@/core/sentry') as typeof import('@/core/sentry');
    captureDiagLog('app', message, data);
  } catch {
    /* Sentry 未启用时忽略 */
  }
}

function trailSentryWs(scope: string, message: string, raw?: unknown): void {
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { captureWsLog } = require('@/core/sentry') as typeof import('@/core/sentry');
    captureWsLog(
      scope,
      message,
      raw,
      raw === undefined ? undefined : safeJson(raw),
    );
  } catch {
    /* Sentry 未启用时忽略 */
  }
}

function trailSentryHttp(entry: HttpLogEntry, reqText: string, resText: string): void {
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { captureHttpLog } = require('@/core/sentry') as typeof import('@/core/sentry');
    captureHttpLog({
      method: entry.method,
      path: entry.path,
      status: entry.status,
      durationMs: entry.durationMs,
      error: entry.error,
      reqText,
      resText,
    });
  } catch {
    /* Sentry 未启用时忽略 */
  }
}

/**
 * 生产环境 console 镜像的长度上限。
 *
 * 大 payload 镜像到 console 在生产是三重浪费：
 *   1. Sentry 开了 enableAutoConsoleLogs，会把每条 console.* 再抓成一条结构化日志，
 *      而同一份 req/res 已经由 captureHttpLog 单独上报过了——纯重复；
 *   2. 浏览器会保留 console 参数，阻止这批字符串被回收；
 *   3. 成本随数据量线性放大：会话多的账号 claimed/list 出参能到几十 KB，
 *      正好落在刷新后用户开始打字的窗口里。
 * 完整内容仍然写进本地诊断日志（我的页可导出），排查不受影响。
 */
const CONSOLE_MIRROR_MAX_CHARS = 2_000;

function mirrorToConsole(level: 'log' | 'warn', line: string): void {
  const text =
    __DEV__ || line.length <= CONSOLE_MIRROR_MAX_CHARS
      ? line
      : `${line.slice(0, CONSOLE_MIRROR_MAX_CHARS)}…[console 已省略 ${
          line.length - CONSOLE_MIRROR_MAX_CHARS
        } 字符，完整内容见导出的诊断日志]`;
  if (level === 'warn') console.warn(text);
  else console.log(text);
}

export function logWs(scope: string, message: string, raw?: unknown): void {
  const body =
    raw === undefined
      ? `[ws][${scope}] ${message}`
      : `[ws][${scope}] ${message} raw=${safeJson(raw)}`;
  mirrorToConsole(/^\s*WARN\b/i.test(message) ? 'warn' : 'log', body);
  enqueue('ws', body);
  trailSentryWs(scope, message, raw);
}

export function logHttp(entry: HttpLogEntry): void {
  // 格式：时间前缀在 buildLogRecord 中追加
  // METHOD 接口后缀 ——入参—— {...} ——出参—— {...}
  const reqText = entry.req !== undefined ? safeJson(entry.req) : '';
  const outText =
    entry.res !== undefined
      ? safeJson(entry.res)
      : entry.error
        ? safeJson({ error: entry.error, status: entry.status })
        : '';
  const statusPart = entry.status != null ? ` status=${entry.status}` : '';
  const body =
    `${entry.method.toUpperCase()} ${entry.path}${statusPart}` +
    ` ——入参—— ${reqText}` +
    ` ——出参—— ${outText}`;
  const isError = entry.status == null || entry.status === 0 || entry.status >= 400;
  mirrorToConsole(isError ? 'warn' : 'log', `[http] ${body}`);
  enqueue('http', body);
  trailSentryHttp(entry, reqText, outText);
}

export function logApp(message: string, extra?: unknown): void {
  const body =
    extra === undefined
      ? `[app] ${message}`
      : `[app] ${message} ${safeJson(extra)}`;
  mirrorToConsole('log', body);
  enqueue('app', body);
  trailSentryApp(
    message,
    extra === undefined ? undefined : { preview: safeJson(extra).slice(0, 400) },
  );
}

export async function getLocalLogStats(): Promise<{
  fileCount: number;
  totalBytes: number;
  files: { name: string; size: number }[];
}> {
  await ensureReady();
  await pruneOldFiles();
  const files = await logStore.listFiles();
  const totalBytes = files.reduce((sum, f) => sum + f.size, 0);
  return {
    fileCount: files.length,
    totalBytes,
    files: files.map((f) => ({ name: f.name, size: f.size })),
  };
}

export async function clearLocalLogs(): Promise<void> {
  await flushLocalLogs();
  await ensureReady();
  const files = await logStore.listFiles();
  for (const f of files) {
    await logStore.deleteFile(f.uri);
  }
  for (const c of LOG_CHANNELS) queues[c] = [];
  pruneDone = false;
}

/**
 * 按时间范围导出日志为 zip：内含按「YYYY-MM-DD_HH_类型.txt」分开的文件（ws / http / app）。
 * Native 走系统分享；Web 触发浏览器下载。
 */
export async function exportLocalLogs(
  range: LogExportRange,
): Promise<{ ok: boolean; message: string }> {
  const rangeLabel = LOG_EXPORT_RANGE_LABEL[range];
  const storageBackend =
    Platform.OS === 'web' ? 'IndexedDB（分块 append）' : '本地文件系统（documentDirectory/logs）';
  console.log('[LocalLog] 导出诊断日志', {
    storageBackend,
    platform: Platform.OS,
    range,
  });

  await flushLocalLogs();
  await ensureReady();
  await pruneOldFiles();
  const files = (await logStore.listFiles()).filter((f) =>
    isWithinExportRange(f.dateKey, range),
  );
  if (files.length === 0) {
    return {
      ok: false,
      message:
        range === 'all'
          ? '暂无本地日志可导出'
          : `暂无${rangeLabel}的本地日志可导出`,
    };
  }

  const encoder = new TextEncoder();
  const entries: { name: string; data: Uint8Array }[] = [];
  for (const f of files) {
    const content = await logStore.readFile(f.uri);
    // 统一导出为 .txt
    const exportName = f.name.replace(/\.log$/i, '.txt');
    entries.push({ name: exportName, data: encoder.encode(content) });
  }

  const { buildZipStore } = await import('./zip-store');
  const zipBytes = buildZipStore(entries);
  const stamp = formatLogHourKey().replace(/[-_]/g, '');
  const zipName = `qinghui-logs-${range}-${stamp}.zip`;
  const countHint = `内含 ${entries.length} 个文件，${rangeLabel}`;

  if (Platform.OS === 'web') {
    try {
      const blob = new Blob([new Uint8Array(zipBytes)], { type: 'application/zip' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = zipName;
      a.rel = 'noopener';
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      return {
        ok: true,
        message: `已下载 ${zipName}（${countHint}）`,
      };
    } catch (e) {
      return {
        ok: false,
        message: e instanceof Error ? e.message : '浏览器下载失败',
      };
    }
  }

  try {
    const available = await Sharing.isAvailableAsync();
    if (!available) {
      return { ok: false, message: '当前设备不支持系统分享，无法导出日志' };
    }
    const uri = await logStore.writeTempExportFile(zipName, zipBytes);
    await Sharing.shareAsync(uri, {
      dialogTitle: '导出诊断日志',
      mimeType: 'application/zip',
      UTI: 'public.zip-archive',
    });
    return {
      ok: true,
      message: `已调起分享 ${zipName}（${countHint}）`,
    };
  } catch (e) {
    return {
      ok: false,
      message: e instanceof Error ? e.message : '导出失败',
    };
  }
}
