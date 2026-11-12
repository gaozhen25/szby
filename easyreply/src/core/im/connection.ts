import { AppState, Platform, type AppStateStatus } from 'react-native';
import NetInfo, { type NetInfoState } from '@react-native-community/netinfo';
import { getToken } from '@/core/auth';
import { buildImWsUrl, getAgentId, getTenantId, isImWsUrlConfigured } from './config';
import { createPingFrame, createPongFrame, decodeFrame, encodeFrame } from './protocol';
import { createTransport, type IMTransport, type TransportEvent } from './transport';
import { calcBackoffDelay, generateRequestId, imCaptureError, imLog, imWarn } from './utils';
import { flushHeartbeatStats, recordHeartbeat } from './heartbeat-log';
import {
  logWindowBackground,
  logWindowForeground,
  logWsBackgroundReconnected,
  logWsConnectFailed,
  logWsDisconnected,
} from './ws-diagnostic-log';
import type { ConnectionState, IMConnectionEvent, IMConnectionListener, IMConnectionOptions, IMFrame } from './types';
import {
  decideKeepaliveOnResume,
  getHeartbeatIntervalMs,
  getHeartbeatTimeoutMs,
  getNetworkRestoreDelayMs,
  getWsKeepaliveProfile,
  hasHitHardReconnectLimit,
  isPostSuspendRecoveryReason,
  resolveNetworkFingerprint,
  shouldEnterSoftTimeout,
  shouldPauseHeartbeatTimeoutWhileHidden,
  WS_READY_OPEN,
  type WsKeepaliveProfile,
} from './ws-keepalive';

// Web 默认会周期性 HEAD `/` 做可达性探测，与业务无关且易在 Network 刷红；改用浏览器 online/offline 即可
if (Platform.OS === 'web') {
  NetInfo.configure({ reachabilityShouldRun: () => false });
}

const KEEPALIVE = getWsKeepaliveProfile();

/** 一次网络事件的快照。fingerprint / internetReachable 缺省表示「本次事件不提供该信息」 */
type NetworkSnapshot = {
  online: boolean;
  fingerprint?: string;
  internetReachable?: boolean | null;
  /**
   * 本次事件本身就是「网络刚恢复」的强信号，即使 online 与本地状态相同也要响应。
   * 休眠唤醒时页面进程被冻结过，收不到 offline，online 事件是唯一的恢复通知。
   */
  forceRestore?: boolean;
};

const DEFAULTS: Required<IMConnectionOptions> = {
  heartbeatInterval: KEEPALIVE.heartbeatInterval,
  heartbeatTimeout: KEEPALIVE.heartbeatTimeout,
  reconnectBaseDelay: KEEPALIVE.reconnectBaseDelay,
  reconnectMaxDelay: KEEPALIVE.reconnectMaxDelay,
  maxReconnectAttempts: KEEPALIVE.maxReconnectAttempts,
  ackTimeout: KEEPALIVE.ackTimeout,
  connectedConfirmTimeout: KEEPALIVE.connectedConfirmTimeout,
};

export class IMConnection {
  private transport: IMTransport;
  private options: Required<IMConnectionOptions>;
  private keepalive: WsKeepaliveProfile;
  private listeners = new Set<IMConnectionListener>();
  private state: ConnectionState = 'disconnected';
  private reconnectAttempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private networkRestoreTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private heartbeatTimeoutTimer: ReturnType<typeof setTimeout> | null = null;
  private connectedConfirmTimer: ReturnType<typeof setTimeout> | null = null;
  private connectInFlight = false;
  /** 每轮 openTransport 自增；过期轮次的 connect 结果一律丢弃 */
  private connectEpoch = 0;
  private lastPongAt = 0;
  private lastActivityAt = 0;
  private lastPingPayload: string | null = null;
  private manualClose = false;
  private isNetworkOnline = true;
  /** 网络身份指纹（type / 制式 / SSID / IP），变化即视为链路可能已死 */
  private networkFingerprint: string | null = null;
  /**
   * NetInfo 的上游可达性。只用它的 false→true 跳变触发重连，
   * 绝不用 false 判定离线：误报 false 会直接堵死建连，代价远大于收益。
   */
  private internetReachable: boolean | null = null;
  private lastNetworkSwitchAt = 0;
  private transportErrorProbeTimer: ReturnType<typeof setTimeout> | null = null;
  private suspendCheckTimer: ReturnType<typeof setInterval> | null = null;
  private lastSuspendTickAt = 0;
  private isBackgrounded = false;
  private backgroundedAt: number | null = null;
  private appStateSub: ReturnType<typeof AppState.addEventListener> | null = null;
  private netInfoUnsub: (() => void) | null = null;
  private visibilityUnsub: (() => void) | null = null;
  private transportUnsub: (() => void) | null = null;
  private lastForegroundAt = 0;
  /** 主动 close / teardown 前标记，供 close 事件归类断连原因 */
  private pendingDisconnectTrigger: string | null = null;
  /** 最近一次休眠 / 冻结恢复的墙钟；窗口内握手失败按「网卡未就绪」处理 */
  private resumedAt: number | null = null;
  /** 本次恢复对应的墙钟跳变（小时级则跳过 probe，直接拆线） */
  private lastSuspendDriftMs = 0;
  /**
   * 休眠恢复时页面仍 hidden：先不握手，等可见 / 窗口 focus 再连。
   * Chrome 后台标签里的 WebSocket 经常一直 CONNECTING，把前台重连卡住。
   */
  private pendingVisibleReconnect = false;
  private pageLifecycleUnsub: (() => void) | null = null;

  constructor(transport?: IMTransport, options?: IMConnectionOptions) {
    this.transport = transport ?? createTransport();
    this.keepalive = getWsKeepaliveProfile();
    this.options = { ...DEFAULTS, ...options };
    this.setupAppStateListener();
    this.setupNetworkListener();
    this.setupVisibilityListener();
    this.setupPageLifecycleListener();
    this.startSuspendWatch();
  }

  getState(): ConnectionState { return this.state; }
  getOptions(): Required<IMConnectionOptions> { return this.options; }
  isOnline(): boolean { return this.isNetworkOnline; }
  /** 传输层是否处于 WebSocket.OPEN */
  isTransportOpen(): boolean {
    return this.transport.getReadyState() === WS_READY_OPEN;
  }

  /**
   * 发送前等待业务 connected 且传输层 OPEN。
   * 若已假死 / 断开，会主动拉起 connect / forceReconnect，超时则抛错。
   */
  async waitUntilConnected(timeoutMs = 15_000): Promise<void> {
    if (this.manualClose) {
      throw new Error('[IM] Connection manually closed');
    }
    if (!this.isNetworkOnline) {
      throw new Error('[IM] Network offline');
    }

    if (this.state === 'connected' && this.isTransportOpen()) return;

    // 业务标 connected 但 socket 已死 → 立即拆线重连
    if (this.state === 'connected' && !this.isTransportOpen()) {
      void this.forceReconnect('wait_until_not_open');
    } else if (this.state === 'disconnected') {
      void this.connect();
    } else if (this.state === 'connection_timeout') {
      void this.retry();
    }
    // connecting / reconnecting：交给现有流程，只等待

    await new Promise<void>((resolve, reject) => {
      let settled = false;
      const finish = (fn: () => void) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        unsub();
        fn();
      };

      const timer = setTimeout(() => {
        finish(() => reject(new Error(`[IM] Wait for connection timed out (>${timeoutMs}ms)`)));
      }, timeoutMs);

      const unsub = this.subscribe((event) => {
        if (event.type !== 'state_change') return;
        if (event.state === 'connected' && this.isTransportOpen()) {
          finish(() => resolve());
        }
      });

      // 订阅后再读一次，避免建连刚好落在 check 与 subscribe 之间
      if (this.state === 'connected' && this.isTransportOpen()) {
        finish(() => resolve());
      }
    });
  }

  subscribe(listener: IMConnectionListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  async connect(): Promise<void> {
    if (!isImWsUrlConfigured()) { imWarn('连接层', 'WebSocket 地址未配置，已跳过连接'); return; }
    if (!getAgentId()) { imWarn('连接层', 'agent_id 未设置，请先登录后再连接 WS'); return; }
    if (!getToken()) { imWarn('连接层', 'token 未设置，请先登录后再连接 WS'); return; }
    if (!this.isNetworkOnline) { imWarn('连接层', '网络已断开，暂不连接，等待网络恢复'); this.manualClose = false; this.setState('disconnected'); return; }
    if (this.state === 'connected') { imLog('连接层', '已处于业务 connected，跳过重复连接'); return; }
    if (this.connectInFlight || this.reconnectTimer != null) { imLog('连接层', '连接/重连进行中，跳过重复请求'); return; }
    if (this.state === 'connecting') { imLog('连接层', '正在等待服务端 connected 确认，跳过重复请求'); return; }
    imLog('连接层', '收到连接请求，准备建立 WebSocket', { agent_id: getAgentId(), tenant_id: getTenantId() });
    this.manualClose = false;
    this.clearReconnectTimer();
    await this.openTransport();
  }

  /** 重连次数达上限后，由用户手动触发重试 */
  async retry(): Promise<void> {
    if (!isImWsUrlConfigured()) { imWarn('连接层', 'WebSocket 地址未配置，无法重试'); return; }
    if (!this.isNetworkOnline) { imWarn('连接层', '网络已断开，无法重试'); return; }
    imLog('连接层', '用户手动重试连接，已重置重连计数');
    this.manualClose = false;
    this.reconnectAttempt = 0;
    this.clearReconnectTimer();
    this.clearNetworkRestoreTimer();
    this.clearTransportErrorProbeTimer();
    this.connectInFlight = false;
    this.clearConnectedConfirmTimer();
    this.stopHeartbeat();
    this.teardownTransport('user_retry');
    await this.openTransport();
  }

  disconnect(): void {
    imLog('连接层', '主动断开连接');
    this.manualClose = true;
    this.markDisconnectTrigger('user_manual');
    this.connectInFlight = false;
    this.clearReconnectTimer();
    this.clearNetworkRestoreTimer();
    this.clearTransportErrorProbeTimer();
    this.clearConnectedConfirmTimer();
    this.stopHeartbeat();
    this.teardownTransport();
    this.setState('disconnected');
  }

  sendFrame(frame: IMFrame): void {
    // 业务帧发送前强制 OPEN；避免 state=connected 但 socket 已死时抛难懂错误
    if (frame.type !== 'ping' && frame.type !== 'pong' && !this.isTransportOpen()) {
      throw new Error('[IM] WebSocket is not open');
    }
    // ping/pong：只计数，不落盘（避免心跳刷爆日志）
    if (frame.type === 'ping') {
      recordHeartbeat('ping_sent');
      this.transport.send(encodeFrame(frame));
      return;
    }
    if (frame.type === 'pong') {
      recordHeartbeat('pong_sent');
      this.transport.send(encodeFrame(frame));
      return;
    }
    // send_message / echo_response / ack 等由会话层记语义，连接层不再重复打 type
    this.transport.send(encodeFrame(frame));
  }

  destroy(): void {
    this.disconnect();
    this.stopSuspendWatch();
    this.appStateSub?.remove();
    this.appStateSub = null;
    this.netInfoUnsub?.();
    this.netInfoUnsub = null;
    this.visibilityUnsub?.();
    this.visibilityUnsub = null;
    this.pageLifecycleUnsub?.();
    this.pageLifecycleUnsub = null;
    this.listeners.clear();
  }

  /**
   * 靠墙钟跳变识别设备休眠 / 页面被深度节流后的恢复。
   * 电脑合盖休眠时整个页面进程被冻结：可见性没变所以 visibilitychange 不触发，
   * 没先收到 offline 所以 online 事件也会被「状态未变」挡掉。唤醒瞬间积压的定时器
   * 集中触发，心跳超时立刻拆线重连，而此时网卡还没关联好，连续几次握手超时
   * 就把退避推到了上限——等网络真正就绪时，只能干等一整轮 30s。
   */
  private startSuspendWatch(): void {
    if (this.suspendCheckTimer) return;
    this.lastSuspendTickAt = Date.now();
    this.suspendCheckTimer = setInterval(() => {
      const now = Date.now();
      const drift = now - this.lastSuspendTickAt;
      this.lastSuspendTickAt = now;
      if (drift < this.keepalive.suspendDetectThreshold) return;
      this.handleSuspendResume(drift);
    }, this.keepalive.suspendCheckInterval);
  }

  private stopSuspendWatch(): void {
    if (this.suspendCheckTimer) {
      clearInterval(this.suspendCheckTimer);
      this.suspendCheckTimer = null;
    }
  }

  /**
   * 墙钟跳变可能是合盖休眠，也可能只是后台定时器被节流。
   * 连接仍 OPEN 且跳变未到「长挂起」量级时不当休眠，避免回前台误拆线。
   */
  private handleSuspendResume(driftMs: number): void {
    if (this.manualClose) return;
    if (
      this.state === 'connected'
      && this.isTransportOpen()
      && driftMs < this.keepalive.postSuspendMinBackgroundMs
    ) {
      imLog('保活', '后台定时器节流导致墙钟跳变，连接仍存活，不按休眠处理', {
        driftMs,
        state: this.state,
        readyState: this.transport.getReadyState(),
      });
      return;
    }
    imWarn('保活', '检测到设备休眠 / 长时间挂起后恢复，重置退避并等网卡就绪后再连', {
      driftMs,
      state: this.state,
      readyState: this.transport.getReadyState(),
      attempts: this.reconnectAttempt,
    });
    this.beginPostSuspendRecovery('device_resumed', driftMs);
  }

  private isInPostSuspendWindow(): boolean {
    if (this.resumedAt == null) return false;
    return Date.now() - this.resumedAt < this.keepalive.postSuspendWindowMs;
  }

  /** Web：标签在后台或窗口失焦时不要发起握手 */
  private isPageHidden(): boolean {
    if (Platform.OS !== 'web' || typeof document === 'undefined') return false;
    return document.visibilityState === 'hidden';
  }

  /**
   * 休眠 / 冻结 / 长时间挂起后的统一入口：
   * 先等网卡关联，再由 scheduleNetworkRestoreReconnect 决定 probe 还是拆线。
   * 唤醒瞬间立刻握手，几乎必然 10s 超时，连续几次就把退避推高。
   */
  private beginPostSuspendRecovery(reason: string, driftMs?: number): void {
    if (this.manualClose) return;
    this.resumedAt = Date.now();
    if (typeof driftMs === 'number' && driftMs > this.lastSuspendDriftMs) {
      this.lastSuspendDriftMs = driftMs;
    }
    this.reconnectAttempt = 0;
    this.clearReconnectTimer();
    this.clearHeartbeatTimeout();
    this.scheduleNetworkRestoreReconnect(reason);
  }

  /**
   * Page Lifecycle：电脑休眠 / 浏览器冻结标签时 visibility 往往不变，
   * freeze/resume 和 pageshow(persisted) 是比 setInterval 跳变更直接的信号。
   */
  private setupPageLifecycleListener(): void {
    if (Platform.OS !== 'web' || typeof document === 'undefined' || typeof window === 'undefined') {
      return;
    }
    const onFreeze = () => {
      imLog('保活', '页面进入 freeze，系统即将挂起本进程', {
        state: this.state,
        readyState: this.transport.getReadyState(),
      });
    };
    const onResume = () => {
      if (this.manualClose) return;
      const driftMs = this.lastSuspendTickAt
        ? Date.now() - this.lastSuspendTickAt
        : this.keepalive.suspendDetectThreshold;
      imWarn('保活', '页面从 freeze 恢复', { driftMs, state: this.state });
      this.lastSuspendTickAt = Date.now();
      this.beginPostSuspendRecovery('page_lifecycle_resume', driftMs);
    };
    const onPageShow = (event: Event) => {
      const persisted = typeof event === 'object' && event != null && 'persisted' in event
        ? Boolean((event as PageTransitionEvent).persisted)
        : false;
      if (!persisted || this.manualClose) return;
      imWarn('保活', 'pageshow persisted，从往返缓存恢复', { state: this.state });
      this.beginPostSuspendRecovery('pageshow_bfcache');
    };
    document.addEventListener('freeze', onFreeze);
    document.addEventListener('resume', onResume);
    window.addEventListener('pageshow', onPageShow);
    this.pageLifecycleUnsub = () => {
      document.removeEventListener('freeze', onFreeze);
      document.removeEventListener('resume', onResume);
      window.removeEventListener('pageshow', onPageShow);
    };
  }

  private setupAppStateListener(): void {
    this.appStateSub = AppState.addEventListener('change', (next: AppStateStatus) => {
      if (next === 'active') {
        this.onForeground('appstate');
        return;
      }
      if (next === 'background' || next === 'inactive') {
        this.onBackground('appstate', next);
      }
    });
  }

  private setupVisibilityListener(): void {
    if (Platform.OS !== 'web' || typeof document === 'undefined' || typeof window === 'undefined') {
      return;
    }
    const onVisible = () => {
      if (document.visibilityState === 'hidden') {
        this.onBackground('visibility', 'hidden');
        return;
      }
      if (document.visibilityState === 'visible') {
        this.onForeground('visibility');
      }
    };
    /**
     * 切到别的 App 时 Chrome 常保持 visibilityState=visible（窗口没最小化、标签也没切走）。
     * 这时休眠再点回浏览器不会有 visibilitychange，只能靠 window focus。
     */
    const onFocus = () => this.onForeground('window_focus');
    const onBlur = () => this.onBackground('window_blur', 'blur');
    document.addEventListener('visibilitychange', onVisible);
    window.addEventListener('focus', onFocus);
    window.addEventListener('blur', onBlur);
    this.visibilityUnsub = () => {
      document.removeEventListener('visibilitychange', onVisible);
      window.removeEventListener('focus', onFocus);
      window.removeEventListener('blur', onBlur);
    };
  }

  private onBackground(source: string, detail: string): void {
    if (this.isBackgrounded) return;
    this.isBackgrounded = true;
    this.backgroundedAt = Date.now();
    // 后台切换为 60s ping；仅暂停 pong 超时判定，ping/pong 日志不断
    this.clearHeartbeatTimeout();
    this.restartHeartbeatIfConnected();
    logWindowBackground({
      source,
      detail,
      backgroundedAt: this.backgroundedAt,
      state: this.state,
      readyState: this.transport.getReadyState(),
      networkOnline: this.isNetworkOnline,
    });
    imLog('保活', '进入后台，心跳间隔切换为 60s', {
      source,
      detail,
      intervalMs: getHeartbeatIntervalMs(this.keepalive, true),
    });
  }

  private onForeground(source: string): void {
    const wasBackgrounded = this.isBackgrounded;
    this.isBackgrounded = false;
    const backgroundedAt = this.backgroundedAt;
    this.backgroundedAt = null;

    if (this.manualClose) return;

    // Web 上 AppState + visibility 可能连发，短时间去重
    const now = Date.now();
    if (now - this.lastForegroundAt < 400) {
      imLog('保活', '回前台事件去重，跳过', { source });
      return;
    }
    this.lastForegroundAt = now;

    // 回前台重置重连计数，尽量自动拉起
    if (this.state === 'connection_timeout' || this.reconnectAttempt > 0) {
      this.reconnectAttempt = 0;
    }

    const backgroundDurationMs =
      wasBackgrounded && backgroundedAt != null ? now - backgroundedAt : null;
    const longAway =
      this.pendingVisibleReconnect ||
      this.isInPostSuspendWindow() ||
      (backgroundDurationMs != null &&
        backgroundDurationMs >= this.keepalive.postSuspendMinBackgroundMs);

    const action = decideKeepaliveOnResume({
      manualClose: this.manualClose,
      state: this.state,
      transportReadyState: this.transport.getReadyState(),
      lastActivityAt: this.lastActivityAt || this.lastPongAt,
      backgroundedAt: wasBackgrounded ? backgroundedAt : null,
      longAway,
    }, this.keepalive);

    logWindowForeground({
      source,
      wasBackgrounded,
      backgroundedAt: wasBackgrounded ? backgroundedAt : null,
      backgroundDurationMs,
      state: this.state,
      readyState: this.transport.getReadyState(),
      networkOnline: this.isNetworkOnline,
      resumeAction: action,
    });

    imLog('保活', `回前台决策=${action}`, {
      source,
      state: this.state,
      readyState: this.transport.getReadyState(),
      wasBackgrounded,
      backgroundDurationMs,
    });

    // 回前台恢复 30s 心跳间隔
    this.restartHeartbeatIfConnected();

    // 休眠恢复时曾在后台推迟过握手：人已经回来再决定。
    // 连接仍 OPEN 说明只是误判的后台节流，探活即可，不要拆掉还能用的 socket。
    if (this.pendingVisibleReconnect) {
      this.pendingVisibleReconnect = false;
      if (this.state === 'connected' && this.isTransportOpen()) {
        this.sendHeartbeat({
          reason: 'foreground_probe',
          forceReconnectOnFail: true,
          timeoutMs: this.keepalive.probeTimeout,
        });
        return;
      }
      void this.forceReconnect('visible_after_suspend');
      return;
    }

    // 整晚挂起后第一次回前台：仅当连接已经不健康时才走休眠恢复。
    // 仍 OPEN 则交给下面的 probe，避免切出去几分钟被整段拆线。
    if (
      longAway
      && !this.isInPostSuspendWindow()
      && !(this.state === 'connected' && this.isTransportOpen())
    ) {
      this.beginPostSuspendRecovery('foreground_long_away', backgroundDurationMs ?? undefined);
      return;
    }
    if (this.isInPostSuspendWindow() && this.networkRestoreTimer != null) {
      imLog('保活', '休眠恢复冷却中，回前台不打断等待', { source });
      return;
    }

    if (action === 'reconnect') {
      void this.forceReconnect('foreground_transport_dead');
      return;
    }
    if (action === 'probe') {
      this.sendHeartbeat({
        reason: 'foreground_probe',
        forceReconnectOnFail: true,
        timeoutMs: this.keepalive.probeTimeout,
      });
      return;
    }
    if (action === 'connect') {
      if (this.state === 'connection_timeout') void this.retry();
      else void this.connect();
    }
  }

  private restartHeartbeatIfConnected(): void {
    if (this.state !== 'connected') return;
    this.startHeartbeat();
  }

  private async forceReconnect(reason: string): Promise<void> {
    if (this.manualClose) return;
    if (!this.isNetworkOnline) {
      imWarn('保活', '强制重连跳过：网络离线', { reason });
      this.setState('disconnected');
      return;
    }
    imWarn('保活', '强制重连', { reason });
    this.pendingVisibleReconnect = false;
    this.reconnectAttempt = 0;
    this.clearReconnectTimer();
    this.clearNetworkRestoreTimer();
    this.clearTransportErrorProbeTimer();
    this.connectInFlight = false;
    this.clearConnectedConfirmTimer();
    this.stopHeartbeat();
    this.teardownTransport(reason);
    this.setState('reconnecting');
    await this.openTransport();
  }

  private setupNetworkListener(): void {
    const unsubs: Array<() => void> = [];

    unsubs.push(
      NetInfo.addEventListener((state: NetInfoState) => {
        this.handleNetworkChange({
          online: this.resolveNetworkOnline(state),
          fingerprint: resolveNetworkFingerprint(state),
          internetReachable: state.isInternetReachable ?? null,
        });
      }),
    );

    // Web：有 navigator.connection 时 NetInfo 只听 connection.change，WiFi 恢复经常不回调；
    // 补听 window online/offline，并以 navigator.onLine 为准同步状态。
    if (Platform.OS === 'web' && typeof window !== 'undefined') {
      const syncFromBrowser = (event?: Event) => {
        const online = typeof navigator === 'undefined' ? true : navigator.onLine !== false;
        this.handleNetworkChange({
          online,
          // 休眠唤醒不会先发 offline，isNetworkOnline 始终是 true，
          // 不标记的话这个恢复信号会被「状态未变」的早返回吞掉
          forceRestore: event?.type === 'online' && online,
        });
      };
      window.addEventListener('online', syncFromBrowser);
      window.addEventListener('offline', syncFromBrowser);
      unsubs.push(() => {
        window.removeEventListener('online', syncFromBrowser);
        window.removeEventListener('offline', syncFromBrowser);
      });

      // visibility 的网络同步仍保留；探活由 setupVisibilityListener 负责
      if (typeof document !== 'undefined') {
        const onVisible = () => {
          if (document.visibilityState === 'visible') syncFromBrowser();
        };
        document.addEventListener('visibilitychange', onVisible);
        unsubs.push(() => document.removeEventListener('visibilitychange', onVisible));
      }

      syncFromBrowser();
    }

    this.netInfoUnsub = () => {
      for (const off of unsubs) off();
    };
  }

  /** Web 以 navigator.onLine 为准；原生仍用 NetInfo.isConnected */
  private resolveNetworkOnline(state: NetInfoState): boolean {
    if (Platform.OS === 'web') {
      if (typeof navigator !== 'undefined') return navigator.onLine !== false;
      return state.isConnected !== false;
    }
    return state.isConnected !== false;
  }

  private handleNetworkChange(snapshot: NetworkSnapshot): void {
    const { online, fingerprint } = snapshot;
    if (snapshot.internetReachable !== undefined) {
      this.handleInternetReachable(snapshot.internetReachable);
    }
    if (online === this.isNetworkOnline) {
      if (online && fingerprint) this.handleNetworkFingerprint(fingerprint);
      else if (snapshot.forceRestore) this.handleForcedNetworkRestore();
      return;
    }
    this.isNetworkOnline = online;
    if (fingerprint) this.networkFingerprint = fingerprint;
    this.emit({ type: 'network_change', online });
    if (!online) {
      imWarn('网络监听', '检测到网络已断开，暂停心跳与重连，断开当前连接', { online });
      this.markDisconnectTrigger('network_offline');
      this.connectInFlight = false;
      this.clearReconnectTimer();
      this.clearNetworkRestoreTimer();
      this.clearTransportErrorProbeTimer();
      this.clearConnectedConfirmTimer();
      this.stopHeartbeat();
      this.teardownTransport();
      this.setState('disconnected');
      return;
    }
    if (this.manualClose) { imLog('网络监听', '当前为主动断开状态，恢复网络后不自动重连'); return; }
    this.scheduleNetworkRestoreReconnect('network_restored');
  }

  /**
   * 浏览器报告网络恢复，但本地 isNetworkOnline 一直是 true（休眠期间收不到 offline）。
   * 此时退避计数往往已经涨满，若不打断就只能干等一整轮 reconnectMaxDelay。
   */
  private handleForcedNetworkRestore(): void {
    if (this.manualClose || !this.isNetworkOnline) return;
    if (this.state === 'connected' && this.isTransportOpen()) return;
    imLog('网络监听', '浏览器报告网络恢复，打断退避立即重连', {
      state: this.state,
      attempts: this.reconnectAttempt,
    });
    this.reconnectAttempt = 0;
    this.clearReconnectTimer();
    this.scheduleNetworkRestoreReconnect('browser_online_event');
  }

  /**
   * 上游可达性变化。
   * 只处理 false→true：强制门户认证完成、上游链路恢复时，SSID / IP 都没变，
   * 指纹不会动，否则只能干等退避（最长 30s）。
   * false 本身不作为离线依据——NetInfo 误报 false 会让建连被永久堵死。
   */
  private handleInternetReachable(next: boolean | null): void {
    const previous = this.internetReachable;
    this.internetReachable = next;
    if (previous !== false || next !== true) return;
    if (this.manualClose || !this.isNetworkOnline) return;
    if (this.state === 'connected' && this.isTransportOpen()) return;
    imLog('网络监听', '上游可达性恢复，提前触发重连', { state: this.state });
    this.scheduleNetworkRestoreReconnect('internet_reachable_restored');
  }

  /**
   * 网络仍在线但身份变了（WiFi ↔ 蜂窝、换 WiFi、IP 变更）：
   * 旧 socket 通常已死但 readyState 仍是 OPEN，先短超时探活，探活失败再拆线重连。
   */
  private handleNetworkFingerprint(fingerprint: string): void {
    const previous = this.networkFingerprint;
    if (previous === fingerprint) return;
    this.networkFingerprint = fingerprint;
    if (previous == null || this.manualClose) return;

    // 指纹持续抖动时只响应第一次：后续响应会反复重置退避计数，压成紧凑重连循环
    const now = Date.now();
    if (now - this.lastNetworkSwitchAt < this.keepalive.networkSwitchMinInterval) {
      imLog('网络监听', '链路指纹短时间内再次变化，本次不打断当前流程', {
        from: previous,
        to: fingerprint,
      });
      return;
    }
    this.lastNetworkSwitchAt = now;

    imWarn('网络监听', '网络链路发生切换，立即探活当前连接', {
      from: previous,
      to: fingerprint,
      state: this.state,
      readyState: this.transport.getReadyState(),
    });

    if (this.state === 'connected') {
      if (!this.isTransportOpen()) {
        void this.forceReconnect('network_switched_transport_dead');
        return;
      }
      this.sendHeartbeat({
        reason: 'network_switch_probe',
        forceReconnectOnFail: true,
        timeoutMs: this.keepalive.probeTimeout,
      });
      return;
    }
    // 未连上时旧的退避节奏没意义，重置后按新链路立刻重来。
    // connecting / reconnecting 也要走：在飞的 socket 大概率还绑在旧链路上，
    // 否则要等满一整个握手超时（12s）才会重试。
    this.reconnectAttempt = 0;
    this.scheduleNetworkRestoreReconnect('network_switched');
  }

  /** 网络恢复 / 链路切换后延迟建连，吸收切换瞬间 NetInfo 的连续抖动，避免建连风暴 */
  private scheduleNetworkRestoreReconnect(reason: string): void {
    const delay = getNetworkRestoreDelayMs(reason, this.keepalive);
    // 已在等休眠恢复冷却时，不要被 online / 指纹变化把 2.5s 缩短成 500ms
    if (
      this.networkRestoreTimer &&
      this.isInPostSuspendWindow() &&
      delay < this.keepalive.postSuspendSettleMs
    ) {
      imLog('网络监听', '休眠恢复冷却中，忽略更短的重连调度', { reason, delayMs: delay });
      return;
    }
    imLog('网络监听', `${delay}ms 后发起重连`, { reason, delayMs: delay });
    this.clearNetworkRestoreTimer();
    this.networkRestoreTimer = setTimeout(() => {
      this.networkRestoreTimer = null;
      if (this.manualClose || !this.isNetworkOnline) return;
      if (this.isPageHidden()) {
        if (this.state === 'connected' && this.isTransportOpen()) {
          imLog('网络监听', '页面在后台且连接仍 OPEN，不推迟拆线', { reason, state: this.state });
          return;
        }
        this.pendingVisibleReconnect = true;
        imLog('网络监听', '页面仍在后台，推迟到可见后再连', { reason, state: this.state });
        return;
      }
      this.reconnectAttempt = 0;
      const skipProbe =
        isPostSuspendRecoveryReason(reason) &&
        this.lastSuspendDriftMs >= this.keepalive.postSuspendMinBackgroundMs;
      if (this.state === 'connected') {
        // 整晚休眠后 socket 即使仍标 OPEN 也已是僵尸连接，探活只会再空耗 8s
        if (skipProbe) {
          void this.forceReconnect(reason);
          return;
        }
        // 未收到 offline 事件时旧 socket 可能仍标 OPEN 但已死，先探活再决定是否拆
        if (this.isTransportOpen()) {
          this.sendHeartbeat({
            reason: `${reason}_probe`,
            forceReconnectOnFail: true,
            timeoutMs: this.keepalive.probeTimeout,
          });
        } else {
          void this.forceReconnect(reason);
        }
        return;
      }
      if (this.state === 'connection_timeout') {
        void this.forceReconnect(reason);
        return;
      }
      // 在飞的建连可能绑在旧链路上；connect() 会被重复请求守卫挡掉，必须强拆。
      // 过期那一轮的握手结果由 connectEpoch 守卫丢弃。
      if (this.state === 'connecting' || this.state === 'reconnecting') {
        void this.forceReconnect(reason);
        return;
      }
      // 休眠恢复后即使用 connect() 也会被「连接进行中」守卫挡掉，统一强拆
      this.clearReconnectTimer();
      if (isPostSuspendRecoveryReason(reason)) {
        void this.forceReconnect(reason);
        return;
      }
      void this.connect();
    }, delay);
  }

  private clearNetworkRestoreTimer(): void {
    if (this.networkRestoreTimer) {
      clearTimeout(this.networkRestoreTimer);
      this.networkRestoreTimer = null;
    }
  }

  /**
   * 传输层 error 之后的兜底探活。
   * 绝大多数平台 error 后会紧跟 close（由 close 分支走重连），所以先等一拍，
   * 只有仍停留在 connected 时才探活，避免和 close 的重连流程互相抢。
   */
  private scheduleTransportErrorProbe(): void {
    if (this.transportErrorProbeTimer) return;
    this.transportErrorProbeTimer = setTimeout(() => {
      this.transportErrorProbeTimer = null;
      if (this.manualClose || this.state !== 'connected') return;
      if (!this.isTransportOpen()) {
        void this.forceReconnect('transport_error_not_open');
        return;
      }
      imWarn('保活', '传输层报错但连接未关闭，探活确认链路是否存活');
      this.sendHeartbeat({
        reason: 'transport_error_probe',
        forceReconnectOnFail: true,
        timeoutMs: this.keepalive.probeTimeout,
      });
    }, this.keepalive.transportErrorProbeDelay);
  }

  private clearTransportErrorProbeTimer(): void {
    if (this.transportErrorProbeTimer) {
      clearTimeout(this.transportErrorProbeTimer);
      this.transportErrorProbeTimer = null;
    }
  }

  private emit(event: IMConnectionEvent): void { this.listeners.forEach((l) => l(event)); }
  private setState(state: ConnectionState): void {
    if (this.state === state) return;
    this.state = state;
    imLog('连接层', `连接状态变更 -> ${state}`, { state });
    this.emit({ type: 'state_change', state });
  }

  private touchActivity(): void {
    this.lastActivityAt = Date.now();
  }

  private markDisconnectTrigger(trigger: string): void {
    this.pendingDisconnectTrigger = trigger;
  }

  private consumeDisconnectTrigger(): string | null {
    const trigger = this.pendingDisconnectTrigger;
    this.pendingDisconnectTrigger = null;
    return trigger;
  }

  private logTransportClose(code: number, reason: string): void {
    logWsDisconnected({
      trigger: this.consumeDisconnectTrigger(),
      code,
      closeReason: reason,
      state: this.state,
      readyState: this.transport.getReadyState(),
      isBackgrounded: this.isBackgrounded,
      backgroundedAt: this.backgroundedAt,
      networkOnline: this.isNetworkOnline,
      manualClose: this.manualClose,
    });
  }

  private async openTransport(): Promise<void> {
    if (this.connectInFlight) { imLog('连接层', '传输层连接已在进行，跳过'); return; }
    this.connectInFlight = true;
    const epoch = ++this.connectEpoch;
    this.setState(this.reconnectAttempt > 0 || this.state === 'reconnecting' || this.state === 'connection_timeout' ? 'reconnecting' : 'connecting');
    const url = buildImWsUrl(getToken());
    this.teardownTransport('open_transport_reconnect');
    this.transportUnsub = this.transport.subscribe((e) => this.handleTransportEvent(e));
    try {
      const handshakeTimeout = this.isInPostSuspendWindow()
        ? this.keepalive.postSuspendHandshakeTimeout
        : this.keepalive.handshakeTimeout;
      await this.transport.connect(url, handshakeTimeout);
      if (epoch !== this.connectEpoch) { imLog('连接层', '已有更新的建连轮次，丢弃过期握手结果'); return; }
      // 传输层握手成功 ≠ 业务 connected；等待服务端首帧后再标 connected 并启心跳
      imLog('连接层', 'WebSocket 握手成功，等待服务端下发 connected 确认帧', { agent_id: getAgentId(), tenant_id: getTenantId() });
      this.startConnectedConfirmTimer();
    } catch (error) {
      if (epoch !== this.connectEpoch) { imLog('连接层', '已有更新的建连轮次，丢弃过期建连失败'); return; }
      this.connectInFlight = false;
      this.clearConnectedConfirmTimer();
      logWsConnectFailed({
        trigger: 'connect_failed',
        state: this.state,
        readyState: this.transport.getReadyState(),
        networkOnline: this.isNetworkOnline,
        isBackgrounded: this.isBackgrounded,
        backgroundedAt: this.backgroundedAt,
        error,
      });
      imCaptureError('连接层', '建立连接失败，准备重连', error);
      this.emit({ type: 'error', error: error instanceof Error ? error : new Error(String(error)) });
      this.retryAfterHandshakeFailure();
    }
  }

  private onGatewayConnected(frame: IMFrame): void {
    this.clearConnectedConfirmTimer();
    this.connectInFlight = false;
    this.reconnectAttempt = 0;
    this.resumedAt = null;
    this.lastSuspendDriftMs = 0;
    this.pendingVisibleReconnect = false;
    this.touchActivity();
    const connectedPayload = (frame.payload ?? {}) as { agent_id?: string; connection_id?: string };
    imLog('连接层', '建连成功：服务端已确认 connected', { agent_id: connectedPayload.agent_id, connection_id: connectedPayload.connection_id });
    logWsBackgroundReconnected({
      state: this.state,
      readyState: this.transport.getReadyState(),
      networkOnline: this.isNetworkOnline,
      isBackgrounded: this.isBackgrounded,
      backgroundedAt: this.backgroundedAt,
      agentId: connectedPayload.agent_id,
      connectionId: connectedPayload.connection_id,
    });
    this.setState('connected');
    this.startHeartbeat();
    this.emit({ type: 'frame', frame });
  }

  private handleTransportEvent(event: TransportEvent): void {
    switch (event.type) {
      case 'message': {
        const frame = decodeFrame(event.data);
        if (!frame) {
          imCaptureError(
            '连接层',
            '收到无法解析的消息，已忽略',
            new Error('[IM] Failed to decode WS frame'),
            { rawPreview: typeof event.data === 'string' ? event.data.slice(0, 200) : String(event.data).slice(0, 200) },
          );
          return;
        }
        this.touchActivity();
        switch (frame.type) {
          case 'connected':
            this.onGatewayConnected(frame);
            return;
          case 'ping':
            recordHeartbeat('ping_recv');
            try {
              this.sendFrame(createPongFrame(typeof frame.payload === 'string' ? frame.payload : undefined));
            } catch {
              imWarn('保活', '回应服务端 ping 失败，触发重连');
              void this.forceReconnect('pong_send_failed');
            }
            return;
          case 'pong': {
            this.lastPongAt = Date.now();
            this.clearHeartbeatTimeout();
            const matched = this.lastPingPayload != null && frame.payload === this.lastPingPayload;
            recordHeartbeat('pong_recv');
            console.log('\n\n');
            if (!matched) recordHeartbeat('pong_mismatch');
            return;
          }
          case 'error':
            imCaptureError(
              '连接层',
              `服务端返回错误：${frame.code ?? 'unknown'}`,
              new Error(`[IM] Server error frame: ${frame.code ?? 'unknown'} ${frame.message ?? ''}`),
              { code: frame.code, message: frame.message },
            );
            this.emit({ type: 'frame', frame });
            return;
          default:
            // 业务帧正文由会话层统一落盘，连接层不再打「收到下行」避免同帧双打
            this.emit({ type: 'frame', frame });
            return;
        }
      }
      case 'close': {
        // 建连失败 close 在 connectInFlight 内统一记 connect_failed
        if (this.connectInFlight && !this.pendingDisconnectTrigger) {
          this.markDisconnectTrigger('connect_failed');
        }
        // 建连失败由 openTransport catch 统一上报；会话中异常关闭才在这里报
        const abnormal = event.code !== 1000 && event.code !== 1001;
        this.logTransportClose(event.code, event.reason);
        if (abnormal && !this.manualClose && !this.connectInFlight) {
          imCaptureError(
            '连接层',
            `连接异常关闭 code=${event.code}`,
            new Error(`[IM] WebSocket closed: ${event.code}`),
            { code: event.code, reason: event.reason },
          );
        } else {
          imWarn('连接层', `连接关闭 code=${event.code}`, { code: event.code, reason: event.reason });
        }
        const wasConnecting = this.connectInFlight;
        this.connectInFlight = false;
        this.clearConnectedConfirmTimer();
        this.stopHeartbeat();
        if (!this.manualClose) {
          this.setState('reconnecting');
          // 建连失败由 openTransport.catch → retryAfterHandshakeFailure 统一重试，避免和这里抢定时器
          if (!wasConnecting) this.scheduleReconnect();
        } else {
          this.setState('disconnected');
        }
        break;
      }
      case 'error':
        // 建连阶段的 error 会由 openTransport catch 统一上报，避免重复
        if (!this.connectInFlight) {
          if (!this.pendingDisconnectTrigger) this.markDisconnectTrigger('transport_error');
          imCaptureError('连接层', '传输层错误事件', event.error);
          // error 后不一定跟 close，若真不来就得靠这次探活兜底
          this.scheduleTransportErrorProbe();
        } else {
          imWarn('连接层', '传输层错误事件', { error: String(event.error) });
        }
        this.emit({ type: 'error', error: event.error });
        break;
    }
  }

  /**
   * 握手失败后的重试。
   * 休眠唤醒后普通 scheduleReconnect→openTransport 会复用半死的建连状态；
   * 切窗口能连上是因为 forceReconnect 整段拆掉重来。前台可见时走同一条路。
   */
  private retryAfterHandshakeFailure(): void {
    if (this.manualClose) return;
    if (this.isPageHidden()) {
      this.pendingVisibleReconnect = true;
      imLog('连接层', '握手失败且页面在后台，等到可见后再强制重连');
      return;
    }
    if (this.isInPostSuspendWindow() || this.lastSuspendDriftMs > 0) {
      imLog('连接层', '握手失败，按休眠恢复路径强制重连', {
        inWindow: this.isInPostSuspendWindow(),
        driftMs: this.lastSuspendDriftMs,
      });
      this.clearReconnectTimer();
      this.reconnectTimer = setTimeout(() => {
        this.reconnectTimer = null;
        void this.forceReconnect('handshake_timeout_after_suspend');
      }, this.keepalive.postSuspendRetryDelay);
      return;
    }
    this.scheduleReconnect();
  }

  private scheduleReconnect(): void {
    if (this.manualClose) return;
    if (!this.isNetworkOnline) {
      imWarn('连接层', '网络已断开，暂停重连，等待网络恢复后自动重连');
      this.setState('disconnected');
      return;
    }
    if (hasHitHardReconnectLimit(this.reconnectAttempt, this.keepalive)) {
      imCaptureError(
        '连接层',
        `自动重连已达硬上限 ${this.keepalive.maxReconnectAttempts} 次，停止重连`,
        new Error('[IM] Hard reconnect limit reached'),
        { attempts: this.reconnectAttempt, max: this.keepalive.maxReconnectAttempts },
      );
      this.clearReconnectTimer();
      this.connectInFlight = false;
      this.setState('connection_timeout');
      return;
    }

    const postSuspendRetry = this.isInPostSuspendWindow();
    const softTimeout = !postSuspendRetry && shouldEnterSoftTimeout(this.reconnectAttempt, this.keepalive);
    const delay = postSuspendRetry
      ? this.keepalive.postSuspendRetryDelay
      : softTimeout
        ? this.keepalive.stalledRetryInterval
        : calcBackoffDelay(this.reconnectAttempt, this.options.reconnectBaseDelay, this.options.reconnectMaxDelay);

    if (softTimeout) {
      // UI 提示超时，但继续慢速重试，避免用户必须手动点
      this.setState('connection_timeout');
      imWarn('保活', `连续失败 ${this.reconnectAttempt} 次，进入慢速重试`, {
        delayMs: Math.round(delay),
        softUiTimeoutAttempts: this.keepalive.softUiTimeoutAttempts,
      });
    } else if (postSuspendRetry) {
      this.setState('reconnecting');
      imLog('保活', '休眠恢复窗口内握手失败，短间隔重试（网卡可能尚未就绪）', {
        delayMs: Math.round(delay),
        attempts: this.reconnectAttempt,
      });
    } else {
      this.setState('reconnecting');
    }

    this.clearReconnectTimer();
    this.reconnectTimer = setTimeout(() => {
      this.reconnectAttempt += 1;
      this.reconnectTimer = null;
      imLog('连接层', `开始第 ${this.reconnectAttempt} 次重连（重连后历史消息走 REST 重拉）`, {
        delayMs: Math.round(delay),
        agent_id: getAgentId(),
        softTimeout,
        postSuspendRetry,
      });
      void this.openTransport();
    }, delay);
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private startConnectedConfirmTimer(): void {
    this.clearConnectedConfirmTimer();
    const timeout = this.options.connectedConfirmTimeout;
    this.connectedConfirmTimer = setTimeout(() => {
      this.connectedConfirmTimer = null;
      imWarn('连接层', `等待服务端 connected 确认超时（>${timeout}ms），主动断开并重连`);
      this.markDisconnectTrigger('connect_confirm_timeout');
      this.transport.close(4001, 'connected confirm timeout');
    }, timeout);
  }

  private clearConnectedConfirmTimer(): void {
    if (this.connectedConfirmTimer) {
      clearTimeout(this.connectedConfirmTimer);
      this.connectedConfirmTimer = null;
    }
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.lastPongAt = Date.now();
    this.touchActivity();
    const intervalMs = getHeartbeatIntervalMs(this.keepalive, this.isBackgrounded);
    const phase = this.isBackgrounded ? '后台' : '前台';
    imLog('心跳', `启动心跳定时器（${phase}），间隔 ${intervalMs}ms`);
    this.heartbeatTimer = setInterval(
      () => this.sendHeartbeat({ reason: 'interval' }),
      intervalMs,
    );
  }

  private isHeartbeatTimeoutPaused(): boolean {
    return this.isBackgrounded
      || shouldPauseHeartbeatTimeoutWhileHidden(
        AppState.currentState,
        Platform.OS === 'web' && typeof document !== 'undefined' ? document.visibilityState : null,
      );
  }

  private sendHeartbeat(opts?: {
    reason?: string;
    forceReconnectOnFail?: boolean;
    /** 探活场景传入更短的超时，避免等满常规 pong 超时 */
    timeoutMs?: number;
  }): void {
    if (this.state !== 'connected') return;

    if (this.transport.getReadyState() !== WS_READY_OPEN) {
      imWarn('心跳', '传输层非 OPEN，触发重连', { readyState: this.transport.getReadyState(), reason: opts?.reason });
      void this.forceReconnect('heartbeat_not_open');
      return;
    }

    const isProbe = opts?.timeoutMs != null;
    const payload = generateRequestId();
    this.lastPingPayload = payload;
    const sentAt = Date.now();
    try {
      this.sendFrame(createPingFrame(payload));
    } catch {
      imWarn('心跳', 'ping 发送失败（连接可能已断开）', { reason: opts?.reason });
      if (opts?.forceReconnectOnFail !== false) void this.forceReconnect('ping_send_failed');
      return;
    }

    // 后台仍发 ping 记日志，但不据 pong 超时断连（定时器易被节流）；探活除外
    if (this.isHeartbeatTimeoutPaused() && !isProbe) {
      return;
    }

    const timeoutMs = opts?.timeoutMs ?? getHeartbeatTimeoutMs(this.keepalive, this.isBackgrounded);
    this.clearHeartbeatTimeout();
    this.heartbeatTimeoutTimer = setTimeout(() => {
      if (this.isHeartbeatTimeoutPaused() && !isProbe) return;
      // 探活按「本次 ping 之后是否收到过 pong」判定；常规心跳保留累计静默判定
      const noPongSinceSent = this.lastPongAt < sentAt;
      const stalled = isProbe ? noPongSinceSent : Date.now() - this.lastPongAt >= timeoutMs;
      if (!stalled) return;
      flushHeartbeatStats('pong超时前', true);
      imWarn('心跳', `pong 超时（>${timeoutMs}ms），判定连接异常并触发重连`, {
        lastPongAt: this.lastPongAt,
        reason: opts?.reason,
        isProbe,
      });
      if (opts?.forceReconnectOnFail) {
        void this.forceReconnect(`${opts?.reason ?? 'heartbeat'}_timeout`);
        return;
      }
      this.markDisconnectTrigger('heartbeat_timeout');
      this.transport.close(4000, 'heartbeat timeout');
    }, timeoutMs);
  }

  private clearHeartbeatTimeout(): void {
    if (this.heartbeatTimeoutTimer) {
      clearTimeout(this.heartbeatTimeoutTimer);
      this.heartbeatTimeoutTimer = null;
    }
  }

  private stopHeartbeat(): void {
    flushHeartbeatStats('停止心跳', true);
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
    this.clearHeartbeatTimeout();
  }

  private teardownTransport(reason = 'teardown'): void {
    const rs = this.transport.getReadyState();
    if ((rs === WS_READY_OPEN || rs === 2) && !this.pendingDisconnectTrigger) {
      this.markDisconnectTrigger(reason);
    }
    this.transportUnsub?.();
    this.transportUnsub = null;
    this.transport.close(1000, 'teardown');
  }
}

let _defaultConnection: IMConnection | null = null;
export function getIMConnection(options?: IMConnectionOptions): IMConnection {
  if (!_defaultConnection) _defaultConnection = new IMConnection(undefined, options);
  return _defaultConnection;
}
export function resetIMConnection(): void {
  _defaultConnection?.destroy();
  _defaultConnection = null;
}
export default IMConnection;
