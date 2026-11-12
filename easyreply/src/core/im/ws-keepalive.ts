// ============================================================
// WebSocket 保活策略（iOS / Android / Web）
// - 前台 ping 30s / 后台 ping 60s（后台仍发 ping，日志不断）
// - 后台仅暂停 pong 超时判定，避免定时器节流误杀
// - 回前台：传输层仍 OPEN → probe；失败再 forceReconnect
// - 回前台：传输层已非 OPEN → 直接重连（不因后台停留时长重连）
// ============================================================

import { Platform } from 'react-native';
import type { ConnectionState } from './types';

/** WebSocket.OPEN */
export const WS_READY_OPEN = 1;

export type WsKeepaliveProfile = {
  /** 前台 ping 间隔 */
  foregroundHeartbeatInterval: number;
  /** 后台 ping 间隔 */
  backgroundHeartbeatInterval: number;
  /** 前台单次 ping 等待 pong 超时 */
  foregroundHeartbeatTimeout: number;
  /** 后台单次 ping 等待 pong 超时（仅诊断；后台不据此断连） */
  backgroundHeartbeatTimeout: number;
  /** @deprecated 兼容 IMConnectionOptions，等同 foregroundHeartbeatInterval */
  heartbeatInterval: number;
  /** @deprecated 兼容 IMConnectionOptions，等同 foregroundHeartbeatTimeout */
  heartbeatTimeout: number;
  /**
   * 单次探活 ping 的等待上限。
   * 回前台 / 网络切换后要快速判定链路是否已死，不能等 60s 的常规 pong 超时。
   */
  probeTimeout: number;
  /**
   * WebSocket 握手超时。弱网下 new WebSocket 可能长期无任何事件，
   * 必须自己兜底，否则连接流程会永久卡在 in-flight 而不再重连。
   */
  handshakeTimeout: number;
  /** 网络恢复后延迟建连，吸收 WiFi/蜂窝切换时 NetInfo 的连续抖动 */
  networkRestoreDebounce: number;
  /**
   * 收到传输层 error 后，延迟多久再探活。
   * error 之后通常紧跟 close（由 close 走重连），等一小会儿避免和它抢；
   * 只有「error 来了但 close 一直不来」时才需要这次探活兜底。
   */
  transportErrorProbeDelay: number;
  /**
   * 两次「链路指纹变化」响应之间的最小间隔。
   * 指纹变化会打断在飞的建连并重置退避计数，弱网下指纹可能持续抖动，
   * 没有这个节流就等于废掉指数退避，退化成紧凑重连循环。
   */
  networkSwitchMinInterval: number;
  /** 挂起检测 tick 间隔：靠墙钟跳变识别设备休眠 */
  suspendCheckInterval: number;
  /**
   * 墙钟跳变超过该值，判定设备刚从休眠 / 深度节流恢复。
   * 必须明显高于浏览器后台节流（Chrome 常见把 setInterval 压到约 60s），
   * 否则短时间切后台也会被当成合盖休眠。
   */
  suspendDetectThreshold: number;
  /**
   * 休眠 / 冻结恢复后，第一次握手前先等网卡关联。
   * 500ms 的常规 debounce 远远不够：macOS / Windows 唤醒后
   * navigator.onLine 仍是 true，但 Wi-Fi/有线还要数秒才能真正通。
   */
  postSuspendSettleMs: number;
  /**
   * 恢复后的「网络未就绪」窗口。窗口内握手失败不当成服务端不可用，
   * 不抬指数退避、不进 soft timeout，用短间隔重试。
   */
  postSuspendWindowMs: number;
  /** 恢复窗口内两次握手之间的间隔 */
  postSuspendRetryDelay: number;
  /** 恢复窗口内用更短握手超时，尽快确认网卡是否已通 */
  postSuspendHandshakeTimeout: number;
  /**
   * 后台挂起超过该时长，回前台才按休眠恢复（先等网卡，再拆线重连）。
   * 切去别的 App 几分钟不应触发；合盖过夜远长于这个值。
   */
  postSuspendMinBackgroundMs: number;
  reconnectBaseDelay: number;
  reconnectMaxDelay: number;
  maxReconnectAttempts: number;
  softUiTimeoutAttempts: number;
  stalledRetryInterval: number;
  connectedConfirmTimeout: number;
  ackTimeout: number;
};

export type KeepaliveResumeAction = 'none' | 'connect' | 'probe' | 'reconnect';

export type KeepaliveResumeInput = {
  manualClose: boolean;
  state: ConnectionState;
  transportReadyState: number;
  lastActivityAt: number;
  backgroundedAt: number | null;
  now?: number;
  /** 长时间挂起 / 休眠后回前台：建连中的 OPEN 也可能是僵尸连接，应拆线重连 */
  longAway?: boolean;
};

const BASE_PROFILE = {
  foregroundHeartbeatInterval: 30_000,
  backgroundHeartbeatInterval: 60_000,
  foregroundHeartbeatTimeout: 60_000,
  backgroundHeartbeatTimeout: 120_000,
  probeTimeout: 8_000,
  handshakeTimeout: 12_000,
  networkRestoreDebounce: 500,
  transportErrorProbeDelay: 1_000,
  networkSwitchMinInterval: 3_000,
  suspendCheckInterval: 5_000,
  suspendDetectThreshold: 180_000,
  postSuspendSettleMs: 2_500,
  postSuspendWindowMs: 120_000,
  postSuspendRetryDelay: 2_000,
  postSuspendHandshakeTimeout: 6_000,
  postSuspendMinBackgroundMs: 10 * 60_000,
  reconnectBaseDelay: 1_000,
  reconnectMaxDelay: 30_000,
  maxReconnectAttempts: 0,
  softUiTimeoutAttempts: 8,
  stalledRetryInterval: 15_000,
  connectedConfirmTimeout: 10_000,
  ackTimeout: 10_000,
};

const NATIVE_PROFILE: WsKeepaliveProfile = {
  ...BASE_PROFILE,
  heartbeatInterval: BASE_PROFILE.foregroundHeartbeatInterval,
  heartbeatTimeout: BASE_PROFILE.foregroundHeartbeatTimeout,
};

const WEB_PROFILE: WsKeepaliveProfile = {
  ...NATIVE_PROFILE,
  stalledRetryInterval: 12_000,
  handshakeTimeout: 10_000,
};

export function getWsKeepaliveProfile(
  platform: typeof Platform.OS = Platform.OS,
): WsKeepaliveProfile {
  return platform === 'web' ? WEB_PROFILE : NATIVE_PROFILE;
}

/** 当前应使用的 ping 间隔 */
export function getHeartbeatIntervalMs(
  profile: WsKeepaliveProfile,
  isBackgrounded: boolean,
): number {
  return isBackgrounded
    ? profile.backgroundHeartbeatInterval
    : profile.foregroundHeartbeatInterval;
}

/** 当前应使用的 pong 超时（仅前台用于断连判定） */
export function getHeartbeatTimeoutMs(
  profile: WsKeepaliveProfile,
  isBackgrounded: boolean,
): number {
  return isBackgrounded
    ? profile.backgroundHeartbeatTimeout
    : profile.foregroundHeartbeatTimeout;
}

/** 是否应暂停客户端 pong 超时判定（后台定时器易被节流） */
export function shouldPauseHeartbeatTimeoutWhileHidden(
  appState: string,
  visibilityState?: DocumentVisibilityState | null,
): boolean {
  if (appState === 'background' || appState === 'inactive') return true;
  if (visibilityState === 'hidden') return true;
  return false;
}

/** @deprecated 后台仍发 ping，仅超时判定暂停；保留导出不破坏旧引用 */
export function shouldPauseHeartbeatWhileHidden(
  appState: string,
  visibilityState?: DocumentVisibilityState | null,
): boolean {
  return shouldPauseHeartbeatTimeoutWhileHidden(appState, visibilityState);
}

/** 是否已达硬重连上限（0 表示不限制） */
export function hasHitHardReconnectLimit(
  attempt: number,
  profile: WsKeepaliveProfile,
): boolean {
  return profile.maxReconnectAttempts > 0 && attempt >= profile.maxReconnectAttempts;
}

/** 是否应展示 connection_timeout（仍可继续慢重试） */
export function shouldEnterSoftTimeout(
  attempt: number,
  profile: WsKeepaliveProfile,
): boolean {
  return attempt >= profile.softUiTimeoutAttempts;
}

/** NetInfo 状态的最小子集，避免本模块依赖 NetInfo 类型 */
export type NetworkFingerprintInput = {
  type?: string | null;
  /** NetInfo 的 details 形状随连接类型而变（甚至为 null），运行时按需宽松读取 */
  details?: unknown;
};

/**
 * 网络「身份」指纹。
 * WiFi ↔ 蜂窝切换、换 WiFi、IP 变更后，`isConnected` 往往仍为 true，
 * 但旧 socket 实际已死。指纹变化即可作为主动探活的依据，
 * 避免只能等 30s ping + 60s pong 超时才发现。
 */
export function resolveNetworkFingerprint(state: NetworkFingerprintInput): string {
  const details =
    state.details && typeof state.details === 'object'
      ? (state.details as Record<string, unknown>)
      : {};
  const pick = (key: string): string => {
    const value = details[key];
    return typeof value === 'string' ? value : '';
  };
  return [
    state.type || 'unknown',
    pick('cellularGeneration'),
    pick('ssid'),
    pick('ipAddress'),
  ].join('|');
}

/**
 * 回前台 / 页签可见时的动作决策。
 * - reconnect：仅当传输层已非 OPEN（底层已死）
 * - probe：socket 仍 OPEN → 立刻 ping 探活；失败由连接层 forceReconnect
 *   （后台期间无下行不计入 stale 直重连，避免误拆仍存活的连接）
 * - connect：未连接且非超时硬停 → 发起连接
 *
 * 注意：后台停留时长、lastActivityAt 过旧本身不作为重连依据。
 * 后台仍可能正常收消息；OPEN 时先探活，探活失败再拆。
 */
export function decideKeepaliveOnResume(
  input: KeepaliveResumeInput,
  profile: WsKeepaliveProfile = getWsKeepaliveProfile(),
): KeepaliveResumeAction {
  if (input.manualClose) return 'none';

  const transportOpen = input.transportReadyState === WS_READY_OPEN;

  if (input.state === 'connected') {
    // 仅传输层已死才直接重连；仍 OPEN 则 probe（含后台久无下行场景）
    if (!transportOpen) return 'reconnect';
    return 'probe';
  }

  if (input.state === 'connecting' || input.state === 'reconnecting') {
    // 休眠后 readyState 仍可能是 OPEN，但这是僵尸连接；切窗口能连上就是因为这里拆了它
    if (!transportOpen || input.longAway) return 'reconnect';
    return 'none';
  }

  // disconnected / connection_timeout：回前台尽量拉起
  return 'connect';
}

/** 这些原因意味着刚从休眠 / 冻结 / 长时间挂起回来，网卡多半还没就绪 */
const POST_SUSPEND_REASONS = new Set([
  'device_resumed',
  'page_lifecycle_resume',
  'pageshow_bfcache',
  'foreground_long_away',
  'visible_after_suspend',
]);

export function isPostSuspendRecoveryReason(reason: string): boolean {
  return POST_SUSPEND_REASONS.has(reason);
}

/** 网络恢复后的建连延迟：休眠唤醒要比 Wi-Fi 抖动 debounce 长得多 */
export function getNetworkRestoreDelayMs(
  reason: string,
  profile: WsKeepaliveProfile = getWsKeepaliveProfile(),
): number {
  return isPostSuspendRecoveryReason(reason)
    ? profile.postSuspendSettleMs
    : profile.networkRestoreDebounce;
}
