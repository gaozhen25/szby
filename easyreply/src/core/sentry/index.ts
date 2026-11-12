// ============================================================
// @sentry/react-native 封装模块
// 配置从 根目录 .env → EXPO_PUBLIC_SENTRY_DSN 读取
// Errors（Issues）：test + production；Logs：仅 production
// ============================================================
import type { ComponentType } from 'react';
import * as Sentry from '@sentry/react-native';
import { Platform } from 'react-native';
import Constants from 'expo-constants';
import { APP_ENV } from '@/lib/api-host';

// ---- 从 .env 读取 ----
const SENTRY_DSN: string =
  (process.env.EXPO_PUBLIC_SENTRY_DSN as string) || '';

function getAppEnv(): string {
  // 与启动脚本一致，优先 EXPO_PUBLIC_APP_ENV；Constants 在部分热更场景可能滞后
  return APP_ENV || (Constants.expoConfig?.extra?.env as string) || 'production';
}

function isSentryConfigured(): boolean {
  return !!SENTRY_DSN;
}

/** Errors / Issues：test + production */
function isSentryEnabled(): boolean {
  if (!isSentryConfigured()) return false;
  const env = getAppEnv();
  return env === 'production' || env === 'test';
}

/** Structured Logs + 自动抓 console：仅 production */
function isSentryLogsEnabled(): boolean {
  return isSentryEnabled() && getAppEnv() === 'production';
}

/** Metro / Fast Refresh 开发期错误：不是 App 运行时崩溃，不应拆成多条 Issue */
const METRO_ERROR_TYPES = new Set([
  'UnableToResolveError',
  'TransformError',
  'MissingAssetError',
]);

const METRO_TEXT_RE = [
  /unable to resolve module/i,
  /\[Refresh\] Expected to find the updated module/i,
  /metroHotUpdateModule/i,
  /wrapRoot is not a function/i,
  /No script URL provided/i,
];

type SentryExceptionEvent = {
  message?: string;
  exception?: {
    values?: {
      type?: string;
      value?: string;
      stacktrace?: { frames?: { filename?: string | null; function?: string | null }[] };
    }[];
  };
};

function isMetroDevNoise(event: SentryExceptionEvent): boolean {
  const values = event.exception?.values ?? [];
  if (values.some((v) => v.type && METRO_ERROR_TYPES.has(v.type))) return true;
  const frameText = values
    .flatMap((v) => v.stacktrace?.frames ?? [])
    .map((f) => `${f.filename ?? ''} ${f.function ?? ''}`)
    .join('\n');
  const text = [
    event.message ?? '',
    ...values.map((v) => `${v.type ?? ''} ${v.value ?? ''}`),
    frameText,
  ].join('\n');
  return METRO_TEXT_RE.some((re) => re.test(text));
}

function toError(error: unknown, fallbackMessage: string): Error {
  if (error instanceof Error) return error;
  if (typeof error === 'string' && error.trim()) return new Error(error);
  try {
    return new Error(`${fallbackMessage}: ${JSON.stringify(error)}`);
  } catch {
    return new Error(fallbackMessage);
  }
}

let initialized = false;

/**
 * 尽早初始化 Sentry（在应用根布局的最顶层调用）
 */
export function initSentry(): void {
  const env = getAppEnv();

  if (!isSentryConfigured()) {
    console.log(
      '[Sentry] EXPO_PUBLIC_SENTRY_DSN not set — running without crash reporting.\n' +
        '          Set it in .env to enable.',
    );
    return;
  }

  if (!isSentryEnabled()) {
    console.log('[Sentry] Skipped — env:', env, '(enabled for test/production only)');
    return;
  }

  if (initialized) {
    console.log('[Sentry] Already initialized — env:', env);
    return;
  }

  const appName = (Constants.expoConfig?.extra?.appName as string) || '轻回';
  const appVersion = (Constants.expoConfig?.extra?.appVersion as string) || '1.0.0';
  const releaseName =
    (Constants.expoConfig?.ios?.bundleIdentifier as string | undefined) ||
    (Constants.expoConfig?.android?.package as string | undefined) ||
    'qinghui';

  const logsEnabled = isSentryLogsEnabled();

  const integrations: unknown[] = [
    Sentry.reactNativeErrorHandlersIntegration({
      onerror: true,
      onunhandledrejection: true,
    }),
  ];

  // Web：自动捕获 fetch 4xx/5xx（与 http.ts 手动上报互补；SDK 按 URL 去重）
  if (Platform.OS === 'web' && typeof Sentry.httpClientIntegration === 'function') {
    integrations.push(
      Sentry.httpClientIntegration({
        failedRequestStatusCodes: [[500, 599]],
        failedRequestTargets: [/.*/],
      }),
    );
  }

  Sentry.init({
    dsn: SENTRY_DSN,
    environment: env,
    release: `${releaseName}@${appVersion}`,
    dist: Platform.OS,
    tracesSampleRate: __DEV__ ? 0 : env === 'production' ? 0.2 : 0.05,
    enableNative: Platform.OS !== 'web',
    enableAutoPerformanceTracing: !__DEV__,
    // Logs 仅 production：Sentry.logger + 自动抓 console.*
    enableLogs: logsEnabled,
    enableAutoConsoleLogs: logsEnabled,
    logsOrigin: logsEnabled ? 'all' : undefined,
    // 便于在 Issue 里看到请求 URL / 状态码等上下文
    sendDefaultPii: false,
    integrations: integrations as never,
    beforeSend(event) {
      if (isMetroDevNoise(event)) return null;
      event.tags = {
        ...event.tags,
        platform: Platform.OS,
        platformVersion: String(Platform.Version),
        appVersion,
        appName,
        appEnv: env,
      };
      return event;
    },
    beforeSendLog(log) {
      const msg = log.message ?? '';
      if (METRO_TEXT_RE.some((re) => re.test(msg))) return null;
      return log;
    },
  });

  initialized = true;
  console.log(
    '[Sentry] Initialized — env:', env,
    'platform:', Platform.OS,
    'errors: on',
    'logs:', logsEnabled ? 'on' : 'off',
  );
}

export function wrapRoot<P extends object>(Root: ComponentType<P>): ComponentType<P> {
  if (typeof Root !== 'function') return Root;
  if (!isSentryEnabled()) return Root;
  const wrap = (Sentry as { wrap?: (c: never) => ComponentType<P> }).wrap;
  if (typeof wrap !== 'function') return Root;
  return wrap(Root as never);
}

/**
 * 包装 expo-router 的 ErrorBoundary：页面 render 抛错会被 React 吞掉，
 * 不经 ErrorUtils；必须 wrap 后才能进 Sentry。
 */
export function wrapAppErrorBoundary<P extends object>(
  Original: ComponentType<P>,
): ComponentType<P> {
  if (!isSentryEnabled()) return Original;
  const wrap = Sentry.wrapExpoRouterErrorBoundary;
  if (typeof wrap !== 'function') return Original;
  return wrap(Original as never) as ComponentType<P>;
}

export type CaptureContext = {
  /** 业务来源：http / ws / page / crash / im … */
  source?: string;
  tags?: Record<string, string>;
  extra?: Record<string, unknown>;
  level?: Sentry.SeverityLevel;
};

export function captureError(error: unknown, context?: CaptureContext | Record<string, unknown>): void {
  const err = toError(error, 'Unknown error');
  const ctx = normalizeCaptureContext(context);

  if (!isSentryEnabled()) {
    console.error('[CaptureError]', err.message, ctx);
    return;
  }

  Sentry.withScope((scope) => {
    if (ctx.source) scope.setTag('error_source', ctx.source);
    if (ctx.tags) {
      for (const [k, v] of Object.entries(ctx.tags)) scope.setTag(k, v);
    }
    if (ctx.extra) scope.setExtras(ctx.extra);
    if (ctx.level) scope.setLevel(ctx.level);
    Sentry.captureException(err);
  });
}

function normalizeCaptureContext(
  context?: CaptureContext | Record<string, unknown>,
): CaptureContext {
  if (!context) return {};
  if (
    'source' in context ||
    'tags' in context ||
    'extra' in context ||
    'level' in context
  ) {
    return context as CaptureContext;
  }
  // 兼容旧调用：captureError(err, { path, status })
  return { extra: context };
}

export function captureMessage(
  message: string,
  level: Sentry.SeverityLevel = 'info',
  context?: CaptureContext,
): void {
  if (!isSentryEnabled()) {
    console.log(`[CaptureMessage][${level}]`, message, context);
    return;
  }
  Sentry.withScope((scope) => {
    if (context?.source) scope.setTag('error_source', context.source);
    if (context?.tags) {
      for (const [k, v] of Object.entries(context.tags)) scope.setTag(k, v);
    }
    if (context?.extra) scope.setExtras(context.extra);
    scope.setLevel(level);
    Sentry.captureMessage(message, level);
  });
}

/** HTTP 层：5xx / 网络失败等 */
export function captureHttpError(
  error: unknown,
  meta: { path?: string; status?: number; method?: string },
): void {
  captureError(error, {
    source: 'http',
    level: 'error',
    tags: {
      http_status: String(meta.status ?? ''),
      ...(meta.method ? { http_method: meta.method } : {}),
    },
    extra: { path: meta.path, status: meta.status, method: meta.method },
  });
}

/**
 * IM / WebSocket 异常。
 * 正常断线重连不要调这个；只报「真正异常」：握手失败、硬上限、解析失败、服务端 error 帧等。
 */
export function captureWsError(
  error: unknown,
  meta: {
    scope: string;
    event: string;
    code?: string | number;
    extra?: Record<string, unknown>;
  },
): void {
  captureError(error, {
    source: 'ws',
    level: 'error',
    tags: {
      ws_scope: meta.scope,
      ws_event: meta.event,
      ...(meta.code != null ? { ws_code: String(meta.code) } : {}),
    },
    extra: meta.extra,
  });
}

export function setSentryUser(
  user: { id: string; nickname: string; role?: string | null } | null,
): void {
  if (!isSentryEnabled()) return;
  if (user) {
    Sentry.setUser({ id: user.id, username: user.nickname });
    if (user.role) Sentry.setTag('role', user.role);
  } else {
    Sentry.setUser(null);
  }
}

export function addSentryBreadcrumb(
  message: string,
  category?: string,
  data?: Record<string, unknown>,
): void {
  if (!isSentryEnabled() || !initialized) return;
  Sentry.addBreadcrumb({ message, category, data, level: 'info' });
}

/** Sentry extra 单字段上限（脱敏后的 JSON 文本） */
const SENTRY_TRAFFIC_EXTRA_MAX_CHARS = 8_000;
/** Sentry Message 标题上限 */
const SENTRY_TRAFFIC_TITLE_MAX_CHARS = 240;

const trafficWindowStart: Record<string, number> = {};
const trafficCount: Record<string, number> = {};
/** 未稳定期放宽限流，配合 Logs 试用不限量 */
const TRAFFIC_MAX_HTTP_PER_MIN = 500;
const TRAFFIC_MAX_WS_PER_MIN = 2_000;
const DIAG_MAX_APP_PER_MIN = 500;

function ensureSentryInitialized(): boolean {
  if (!isSentryEnabled()) return false;
  if (!initialized) initSentry();
  return initialized;
}

function ensureSentryLogsReady(): boolean {
  if (!isSentryLogsEnabled()) return false;
  return ensureSentryInitialized();
}

function takeTrafficSlot(bucket: string, maxPerMin: number): boolean {
  const now = Date.now();
  const windowStart = trafficWindowStart[bucket] ?? 0;
  if (now - windowStart > 60_000) {
    trafficWindowStart[bucket] = now;
    trafficCount[bucket] = 0;
  }
  const count = trafficCount[bucket] ?? 0;
  if (count >= maxPerMin) return false;
  trafficCount[bucket] = count + 1;
  return true;
}

function truncateSentryText(text: string, max = SENTRY_TRAFFIC_EXTRA_MAX_CHARS): string {
  if (text.length <= max) return text;
  return `${text.slice(0, max)}…[truncated ${text.length - max} chars]`;
}

type TrafficMessageLevel = 'info' | 'warning' | 'error';

type LogAttributeValue = string | number | boolean;

function toLogAttributes(
  tags: Record<string, string>,
  data: Record<string, unknown>,
): Record<string, LogAttributeValue> {
  const out: Record<string, LogAttributeValue> = { traffic_log: true };
  for (const [k, v] of Object.entries(tags)) {
    out[k] = v;
  }
  for (const [k, v] of Object.entries(data)) {
    if (v === null || v === undefined) continue;
    if (typeof v === 'string') out[k] = truncateSentryText(v);
    else if (typeof v === 'number' || typeof v === 'boolean') out[k] = v;
    else out[k] = truncateSentryText(String(v));
  }
  return out;
}

function emitStructuredLog(level: TrafficMessageLevel, message: string, attributes: Record<string, LogAttributeValue>): void {
  if (level === 'error') Sentry.logger.error(message, attributes);
  else if (level === 'warning') Sentry.logger.warn(message, attributes);
  else Sentry.logger.info(message, attributes);
}

function emitTrafficLog(params: {
  channel: 'http' | 'ws' | 'app';
  title: string;
  breadcrumbCategory: string;
  fingerprint: string[];
  tags: Record<string, string>;
  data: Record<string, unknown>;
  level: TrafficMessageLevel;
  rateBucket: string;
  maxPerMin: number;
}): void {
  if (!ensureSentryInitialized()) return;

  const title = params.title.slice(0, SENTRY_TRAFFIC_TITLE_MAX_CHARS);
  // Breadcrumb 随 Errors 通道保留（test + production），便于 Issue 上下文
  Sentry.addBreadcrumb({
    message: title,
    category: params.breadcrumbCategory,
    data: params.data,
    level: params.level === 'error' ? 'error' : params.level === 'warning' ? 'warning' : 'info',
  });

  if (!ensureSentryLogsReady()) return;
  if (!takeTrafficSlot(params.rateBucket, params.maxPerMin)) return;

  emitStructuredLog(
    params.level,
    `[${params.channel}] ${title}`,
    toLogAttributes(
      { error_source: 'traffic_log', log_channel: params.channel, ...params.tags },
      params.data,
    ),
  );
}

/** HTTP 接口日志：入参/出参（脱敏）+ 状态码，写入 Breadcrumb 与 Message 事件 */
export function captureHttpLog(entry: {
  method: string;
  path: string;
  status?: number;
  req?: unknown;
  res?: unknown;
  error?: string;
  durationMs?: number;
  reqText?: string;
  resText?: string;
}): void {
  const method = entry.method.toUpperCase();
  const path = entry.path.trim();
  const status = entry.status;
  const statusPart = status != null ? ` status=${status}` : '';
  const title = `${method} ${path}${statusPart}`;
  const req =
    entry.reqText?.trim() ||
    (entry.req !== undefined ? truncateSentryText(String(entry.req)) : '');
  const res =
    entry.resText?.trim() ||
    (entry.res !== undefined ? truncateSentryText(String(entry.res)) : '');
  const isError = status == null || status === 0 || status >= 400;
  const level: TrafficMessageLevel =
    status != null && status >= 500 ? 'error' : isError ? 'warning' : 'info';

  emitTrafficLog({
    channel: 'http',
    title,
    breadcrumbCategory: 'http',
    fingerprint: ['qinghui-traffic', 'http', method, path],
    tags: {
      http_method: method,
      http_path: path,
      ...(status != null ? { http_status: String(status) } : {}),
    },
    data: {
      method,
      path,
      status,
      durationMs: entry.durationMs,
      error: entry.error,
      ...(req ? { req } : {}),
      ...(res ? { res } : {}),
    },
    level,
    rateBucket: 'http',
    maxPerMin: TRAFFIC_MAX_HTTP_PER_MIN,
  });
}

/** WebSocket 收发 / 连接日志（脱敏 payload） */
export function captureWsLog(scope: string, message: string, raw?: unknown, rawText?: string): void {
  const scopeKey = scope.trim() || 'unknown';
  const isWarn = /^\s*WARN\b/i.test(message);
  const title = `[${scopeKey}] ${message}`.slice(0, SENTRY_TRAFFIC_TITLE_MAX_CHARS);
  const payload =
    rawText?.trim() ||
    (raw !== undefined ? truncateSentryText(String(raw)) : '');

  emitTrafficLog({
    channel: 'ws',
    title,
    breadcrumbCategory: 'ws',
    fingerprint: ['qinghui-traffic', 'ws', scopeKey],
    tags: {
      ws_scope: scopeKey,
      ...(isWarn ? { ws_warn: '1' } : {}),
    },
    data: payload ? { payload } : {},
    level: isWarn ? 'warning' : 'info',
    rateBucket: 'ws',
    maxPerMin: TRAFFIC_MAX_WS_PER_MIN,
  });
}

/**
 * App 诊断摘要（非 HTTP/WS 流量）。
 * 按 channel 指纹聚合；带每分钟限流。
 */
export function captureDiagLog(
  channel: string,
  message: string,
  data?: Record<string, unknown>,
): void {
  if (channel === 'http' || channel === 'ws') return;
  const text = message.slice(0, SENTRY_TRAFFIC_TITLE_MAX_CHARS);
  emitTrafficLog({
    channel: 'app',
    title: text,
    breadcrumbCategory: channel,
    fingerprint: ['qinghui-diag-log', channel],
    tags: { diag_log: '1' },
    data: data ?? {},
    level: 'info',
    rateBucket: `app:${channel}`,
    maxPerMin: DIAG_MAX_APP_PER_MIN,
  });
}

/** 我的页手动探测：发一条可识别的测试异常 */
export async function sendSentryTestEvent(): Promise<{ ok: boolean; message: string }> {
  const env = getAppEnv();
  if (!isSentryConfigured()) {
    return { ok: false, message: '未配置 EXPO_PUBLIC_SENTRY_DSN' };
  }
  if (!isSentryEnabled()) {
    return {
      ok: false,
      message: `当前环境是 ${env}，Sentry 仅在 test/production 启动。`,
    };
  }
  if (!initialized) {
    initSentry();
  }

  const logsEnabled = isSentryLogsEnabled();

  if (logsEnabled) {
    captureDiagLog('app', `SentryProbe 手动探测 env=${env}`, {
      at: new Date().toISOString(),
      platform: Platform.OS,
    });
    Sentry.logger.info('[SentryProbe] Logs 通道探测', {
      probe: true,
      env,
      platform: Platform.OS,
      at: new Date().toISOString(),
      hint: 'Logs 页搜 SentryProbe 或 traffic_log:true',
    });
  }

  const error = new Error(`[SentryProbe] 轻回手动测试上报 env=${env}`);
  error.name = 'SentryProbeError';
  Sentry.captureException(error, {
    tags: { probe: 'manual', error_source: 'probe' },
    extra: {
      at: new Date().toISOString(),
      platform: Platform.OS,
      env,
      hint: 'Errors 配额满时可能失败；诊断流水请看 Logs 页 traffic_log:true',
    },
  });
  const flushed = await Sentry.flush();
  const logsHint = logsEnabled
    ? 'Logs 页搜 SentryProbe；'
    : 'Logs 仅 production 开启；';
  return {
    ok: !!flushed,
    message: flushed
      ? `已发送 Error 探针（env=${env}）。${logsHint}Issues 搜 SentryProbeError`
      : 'flush 未确认，请稍后到 Sentry 确认',
  };
}

export function getSentryStatus(): {
  configured: boolean;
  enabled: boolean;
  logsEnabled: boolean;
  initialized: boolean;
  env: string;
} {
  return {
    configured: isSentryConfigured(),
    enabled: isSentryEnabled(),
    logsEnabled: isSentryLogsEnabled(),
    initialized,
    env: getAppEnv(),
  };
}

export default {
  initSentry,
  wrapRoot,
  wrapAppErrorBoundary,
  captureError,
  captureMessage,
  captureHttpError,
  captureWsError,
  captureDiagLog,
  captureHttpLog,
  captureWsLog,
  setSentryUser,
  addSentryBreadcrumb,
  sendSentryTestEvent,
  getSentryStatus,
};
