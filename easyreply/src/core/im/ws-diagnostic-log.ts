// ============================================================
// WebSocket 诊断日志：前后台切换 / 断连原因 / 后台停留时长
// 统一走 imLog/imWarn → console + logWs 落盘
// ============================================================

import { Platform } from 'react-native';
import type { ConnectionState } from './types';
import { imLog, imWarn } from './utils';

export type WsReadyStateLabel = 'CONNECTING' | 'OPEN' | 'CLOSING' | 'CLOSED' | 'UNKNOWN';

export type WsDisconnectCategory =
  | 'user_manual'
  | 'network_offline'
  | 'network_fluctuation'
  | 'background_platform_limit'
  | 'server_close'
  | 'heartbeat_timeout'
  | 'foreground_probe_failed'
  | 'client_reconnect'
  | 'connect_failed'
  | 'connect_confirm_timeout'
  | 'unknown';

const DISCONNECT_CATEGORY_LABEL: Record<WsDisconnectCategory, string> = {
  user_manual: '用户主动断开',
  network_offline: '断网',
  network_fluctuation: '网络波动',
  background_platform_limit: '后台状态下浏览器/系统限制',
  server_close: '服务端关闭连接',
  heartbeat_timeout: '心跳 pong 超时',
  foreground_probe_failed: '回前台探活失败',
  client_reconnect: '客户端主动重连',
  connect_failed: '建连失败',
  connect_confirm_timeout: '等待 connected 确认超时',
  unknown: '未知原因',
};

export function labelReadyState(readyState: number): WsReadyStateLabel {
  switch (readyState) {
    case 0:
      return 'CONNECTING';
    case 1:
      return 'OPEN';
    case 2:
      return 'CLOSING';
    case 3:
      return 'CLOSED';
    default:
      return 'UNKNOWN';
  }
}

export function formatBackgroundDuration(ms: number | null | undefined): string | null {
  if (ms == null || ms < 0) return null;
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const min = Math.floor(ms / 60_000);
  const sec = Math.round((ms % 60_000) / 1000);
  return sec > 0 ? `${min}m${sec}s` : `${min}m`;
}

export function classifyDisconnectCategory(input: {
  trigger?: string | null;
  code?: number;
  isBackgrounded: boolean;
  networkOnline: boolean;
  manualClose: boolean;
}): WsDisconnectCategory {
  if (input.manualClose) return 'user_manual';
  if (!input.networkOnline) return 'network_offline';

  const trigger = (input.trigger ?? '').trim();

  if (trigger === 'user_manual') return 'user_manual';
  if (trigger === 'network_offline') return 'network_offline';
  if (trigger === 'heartbeat_timeout') return 'heartbeat_timeout';
  if (trigger === 'foreground_probe_timeout') return 'foreground_probe_failed';
  if (trigger === 'connect_confirm_timeout') return 'connect_confirm_timeout';
  if (trigger === 'connect_failed') return 'connect_failed';
  if (trigger === 'transport_error') return 'network_fluctuation';

  if (
    trigger === 'teardown'
    || trigger.startsWith('foreground_')
    || trigger.includes('reconnect')
    || trigger === 'wait_until_not_open'
    || trigger === 'ping_send_failed'
    || trigger === 'pong_send_failed'
    || trigger === 'heartbeat_not_open'
    || trigger === 'network_restored'
  ) {
    return 'client_reconnect';
  }

  // 后台期间被对端 / 浏览器 / 系统掐断（常见：LB 空闲、页签冻结）
  if (input.isBackgrounded) return 'background_platform_limit';

  if (input.code != null && input.code !== 1000 && input.code !== 1001) {
    // 1006 异常关闭、4000 心跳等在非后台时多为网络或服务端
    if (input.code >= 4000) return 'heartbeat_timeout';
    return 'network_fluctuation';
  }

  return 'unknown';
}

type WsSnapshot = {
  state: ConnectionState;
  readyState: number;
  readyStateLabel: WsReadyStateLabel;
  networkOnline: boolean;
};

function buildWsSnapshot(state: ConnectionState, readyState: number, networkOnline: boolean): WsSnapshot {
  return {
    state,
    readyState,
    readyStateLabel: labelReadyState(readyState),
    networkOnline,
  };
}

/** Web 页签诊断专用计时（仅日志，不影响连接层 backgroundedAt / 重连逻辑） */
type WebBackgroundDiagSession = {
  epoch: number;
  startedAt: number;
  source: string;
  detail: string;
};

let webBackgroundDiagSession: WebBackgroundDiagSession | null = null;

function isWebPlatform(): boolean {
  return Platform.OS === 'web';
}

/** 额外 console.log，便于 DevTools 过滤 [Web后台] */
function webBackgroundConsole(event: string, payload: Record<string, unknown>): void {
  if (!isWebPlatform()) return;
  console.log(`[IM][WS诊断][Web后台] ${event}`, payload);
}

function beginWebBackgroundDiagSession(source: string, detail: string, startedAt: number): void {
  if (!isWebPlatform()) return;
  const epoch = (webBackgroundDiagSession?.epoch ?? 0) + 1;
  webBackgroundDiagSession = { epoch, startedAt, source, detail };
  const payload = {
    epoch,
    source,
    detail,
    startedAt,
    startedAtISO: new Date(startedAt).toISOString(),
  };
  webBackgroundConsole('进入后台，开始计时', payload);
  imLog('WS诊断', '【Web后台】进入后台，开始计时', payload);
}

function elapsedWebBackgroundDiagMs(at = Date.now()): number | null {
  if (!webBackgroundDiagSession) return null;
  return at - webBackgroundDiagSession.startedAt;
}

function resetWebBackgroundDiagTimer(reason: string, at = Date.now()): void {
  if (!isWebPlatform() || !webBackgroundDiagSession) return;
  const previousElapsedMs = at - webBackgroundDiagSession.startedAt;
  webBackgroundDiagSession = {
    ...webBackgroundDiagSession,
    startedAt: at,
  };
  const payload = {
    reason,
    epoch: webBackgroundDiagSession.epoch,
    previousElapsedMs,
    previousElapsed: formatBackgroundDuration(previousElapsedMs),
    resetAt: at,
    resetAtISO: new Date(at).toISOString(),
  };
  webBackgroundConsole('后台重连成功，计时已重置', payload);
  imLog('WS诊断', '【Web后台】后台重连成功，计时已重置', payload);
}

function endWebBackgroundDiagSession(reason: string, at = Date.now()): void {
  if (!isWebPlatform() || !webBackgroundDiagSession) return;
  const elapsedMs = at - webBackgroundDiagSession.startedAt;
  const payload = {
    reason,
    epoch: webBackgroundDiagSession.epoch,
    source: webBackgroundDiagSession.source,
    detail: webBackgroundDiagSession.detail,
    elapsedMs,
    elapsed: formatBackgroundDuration(elapsedMs),
    endedAt: at,
    endedAtISO: new Date(at).toISOString(),
  };
  webBackgroundConsole('回到前台，结束计时', payload);
  imLog('WS诊断', '【Web后台】回到前台，结束计时', payload);
  webBackgroundDiagSession = null;
}

function isLikelySystemBackgroundDisconnect(category: WsDisconnectCategory, manualClose: boolean): boolean {
  if (manualClose) return false;
  return (
    category === 'background_platform_limit'
    || category === 'server_close'
    || category === 'network_fluctuation'
    || category === 'unknown'
  );
}

function logWebBackgroundSystemDisconnect(params: {
  category: WsDisconnectCategory;
  categoryLabel: string;
  trigger?: string | null;
  code?: number;
  closeReason?: string;
  disconnectedAt: number;
  backgroundDurationMs: number | null;
}): void {
  if (!isWebPlatform() || params.backgroundDurationMs == null) return;
  const payload = {
    category: params.category,
    categoryLabel: params.categoryLabel,
    trigger: params.trigger ?? null,
    code: params.code ?? null,
    closeReason: params.closeReason ?? null,
    timeToDisconnectMs: params.backgroundDurationMs,
    timeToDisconnect: formatBackgroundDuration(params.backgroundDurationMs),
    disconnectedAt: params.disconnectedAt,
    disconnectedAtISO: new Date(params.disconnectedAt).toISOString(),
    diagEpoch: webBackgroundDiagSession?.epoch ?? null,
    diagSource: webBackgroundDiagSession?.source ?? null,
  };
  webBackgroundConsole('系统原因掉线，进入后台至断连时长', payload);
  imWarn('WS诊断', '【Web后台】系统原因掉线，进入后台至断连时长', payload);
}

/** 【进入后台】记录进入时间与当前连接快照 */
export function logWindowBackground(params: {
  source: string;
  detail: string;
  backgroundedAt: number;
  state: ConnectionState;
  readyState: number;
  networkOnline: boolean;
}): void {
  beginWebBackgroundDiagSession(params.source, params.detail, params.backgroundedAt);
  imLog('WS诊断', '【进入后台】窗口切换到后台', {
    platform: Platform.OS,
    source: params.source,
    detail: params.detail,
    backgroundedAt: params.backgroundedAt,
    backgroundedAtISO: new Date(params.backgroundedAt).toISOString(),
    ...buildWsSnapshot(params.state, params.readyState, params.networkOnline),
  });
}

/** 【回到前台】记录后台停留时长与当前连接快照 */
export function logWindowForeground(params: {
  source: string;
  wasBackgrounded: boolean;
  backgroundedAt: number | null;
  backgroundDurationMs: number | null;
  state: ConnectionState;
  readyState: number;
  networkOnline: boolean;
  resumeAction?: string;
}): void {
  if (params.wasBackgrounded) {
    endWebBackgroundDiagSession(`foreground:${params.source}`);
  }
  imLog('WS诊断', '【回到前台】窗口切换到前台', {
    platform: Platform.OS,
    source: params.source,
    wasBackgrounded: params.wasBackgrounded,
    backgroundedAt: params.backgroundedAt,
    backgroundedAtISO: params.backgroundedAt ? new Date(params.backgroundedAt).toISOString() : null,
    backgroundDurationMs: params.backgroundDurationMs,
    backgroundDuration: formatBackgroundDuration(params.backgroundDurationMs),
    resumeAction: params.resumeAction ?? null,
    ...buildWsSnapshot(params.state, params.readyState, params.networkOnline),
  });
}

/** 【WS断开】记录断连原因；若处于后台则附带「进入后台多久后被断连」 */
export function logWsDisconnected(params: {
  trigger?: string | null;
  code?: number;
  closeReason?: string;
  state: ConnectionState;
  readyState: number;
  isBackgrounded: boolean;
  backgroundedAt: number | null;
  networkOnline: boolean;
  manualClose: boolean;
}): void {
  const now = Date.now();
  const backgroundDurationMs =
    params.isBackgrounded && params.backgroundedAt != null
      ? now - params.backgroundedAt
      : null;

  const category = classifyDisconnectCategory({
    trigger: params.trigger,
    code: params.code,
    isBackgrounded: params.isBackgrounded,
    networkOnline: params.networkOnline,
    manualClose: params.manualClose,
  });

  const payload = {
    platform: Platform.OS,
    category,
    categoryLabel: DISCONNECT_CATEGORY_LABEL[category],
    trigger: params.trigger ?? null,
    code: params.code ?? null,
    closeReason: params.closeReason ?? null,
    isBackgrounded: params.isBackgrounded,
    backgroundedAt: params.backgroundedAt,
    backgroundedAtISO: params.backgroundedAt ? new Date(params.backgroundedAt).toISOString() : null,
    backgroundDurationMs,
    backgroundDuration: formatBackgroundDuration(backgroundDurationMs),
    disconnectedAt: now,
    disconnectedAtISO: new Date(now).toISOString(),
    ...buildWsSnapshot(params.state, params.readyState, params.networkOnline),
    manualClose: params.manualClose,
  };

  imWarn('WS诊断', `【WS断开】${DISCONNECT_CATEGORY_LABEL[category]}`, payload);

  if (
    params.isBackgrounded
    && isLikelySystemBackgroundDisconnect(category, params.manualClose)
  ) {
    logWebBackgroundSystemDisconnect({
      category,
      categoryLabel: DISCONNECT_CATEGORY_LABEL[category],
      trigger: params.trigger,
      code: params.code,
      closeReason: params.closeReason,
      disconnectedAt: now,
      backgroundDurationMs,
    });
  }
}

/** Web 后台期间 WS 重连成功：诊断计时重置（不影响连接层 backgroundedAt） */
export function logWsBackgroundReconnected(params: {
  state: ConnectionState;
  readyState: number;
  networkOnline: boolean;
  isBackgrounded: boolean;
  backgroundedAt: number | null;
  agentId?: string;
  connectionId?: string;
}): void {
  if (!params.isBackgrounded) return;
  resetWebBackgroundDiagTimer('ws_reconnected');
  imLog('WS诊断', '【Web后台】WS 重连成功', {
    backgroundedAt: params.backgroundedAt,
    backgroundedAtISO: params.backgroundedAt ? new Date(params.backgroundedAt).toISOString() : null,
    elapsedSinceDiagStartMs: elapsedWebBackgroundDiagMs(),
    elapsedSinceDiagStart: formatBackgroundDuration(elapsedWebBackgroundDiagMs()),
    agentId: params.agentId ?? null,
    connectionId: params.connectionId ?? null,
    ...buildWsSnapshot(params.state, params.readyState, params.networkOnline),
  });
}

/** 建连失败（通常无 close 事件） */
export function logWsConnectFailed(params: {
  trigger?: string;
  state: ConnectionState;
  readyState: number;
  networkOnline: boolean;
  isBackgrounded: boolean;
  backgroundedAt: number | null;
  error?: unknown;
}): void {
  const now = Date.now();
  const backgroundDurationMs =
    params.isBackgrounded && params.backgroundedAt != null
      ? now - params.backgroundedAt
      : null;

  imWarn('WS诊断', '【WS断开】建连失败', {
    platform: Platform.OS,
    category: 'connect_failed',
    categoryLabel: DISCONNECT_CATEGORY_LABEL.connect_failed,
    trigger: params.trigger ?? 'connect_failed',
    isBackgrounded: params.isBackgrounded,
    backgroundDurationMs,
    backgroundDuration: formatBackgroundDuration(backgroundDurationMs),
    error: params.error instanceof Error ? params.error.message : String(params.error ?? ''),
    ...buildWsSnapshot(params.state, params.readyState, params.networkOnline),
  });

  if (params.isBackgrounded && backgroundDurationMs != null) {
    logWebBackgroundSystemDisconnect({
      category: 'connect_failed',
      categoryLabel: DISCONNECT_CATEGORY_LABEL.connect_failed,
      trigger: params.trigger ?? 'connect_failed',
      disconnectedAt: now,
      backgroundDurationMs,
    });
  }
}
