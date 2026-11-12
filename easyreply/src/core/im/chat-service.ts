import { isLoggedIn } from '@/core/auth';
import { getIMConnection, resetIMConnection, type IMConnection } from './connection';
import { clearImWsUrlOverride, getAgentId, getImWsUrl, getTenantId, isImWsUrlConfigured, setAgentId, setImWsUrl, setTenantId } from './config';
import { getMessageService } from './message-service';
import { getOutboxQueue, resetOutboxQueue } from './outbox';
import { createEchoResponseFrame, createGatewayAckFrame, createPublishFrame, createResumeFrame, createSendMessageFrame } from './protocol';
import { getSessionService } from './session-service';
import { getSyncService } from './sync';
import { resetIMCache } from './store/im-cache';
import { getIMStore, resetIMStore } from './store/im-store';
import { imLog, imWarn, imCaptureError, parseApiMessageContent } from './utils';
import type { AckPayload, AckResultData, ChatMessage, ConnectionState, Conversation, GatewayInboundMessage, IMGatewayEvent, PublishResultData, ReadPayload, ResumeResultData, SendResultData, SyncResultPayload } from './types';

// 订阅表挂模块级：退出登录会 resetChatService() 重建实例，
// 若挂实例字段，根布局/全局 Store 这类「挂载时注册一次」的订阅方会永久失联。
const gatewayMsgListeners = new Set<(msg: GatewayInboundMessage) => void>();
const gatewayEventListeners = new Set<(evt: IMGatewayEvent) => void>();
/** 帧订阅单槽：热更新重建 ChatService 时先卸旧订阅，避免同帧处理两遍 */
let frameListenerUnsub: (() => void) | null = null;

export class ChatService {
  private connection: IMConnection; private connectionUnsub: (() => void) | null = null; private initialized = false;
  // 联调网关：消费位点跟踪。lastSeq=已收到的最大 seq；nextSeq=下次 resume 起点
  private lastSeq = 0;
  private hasConnectedOnce = false;

  constructor(connection?: IMConnection) { this.connection = connection ?? getIMConnection(); }

  getConnection(): IMConnection { return this.connection; }
  isOnline(): boolean { return this.connection.isOnline(); }
  /**
   * 发送前确保 WS 已业务 connected 且传输层 OPEN。
   * 若断开 / 假死会触发连接层拉起；超时抛错。
   */
  async ensureConnected(timeoutMs = 15_000): Promise<void> {
    if (!this.initialized) this.init();
    await this.connection.waitUntilConnected(timeoutMs);
  }
  configureWsUrl(url: string): void { setImWsUrl(url); }
  clearWsUrlOverride(): void { clearImWsUrlOverride(); }
  getWsUrl(): string { return getImWsUrl(); }
  isWsConfigured(): boolean { return isImWsUrlConfigured(); }

  // ---------- v2 网关：agent_id / tenant_id 配置（联调写死 test_003） ----------
  configureGateway(opts: { agentId?: string; tenantId?: string }): void {
    if (opts.agentId) setAgentId(opts.agentId);
    if (opts.tenantId) setTenantId(opts.tenantId);
    imLog('会话层', '已配置网关 agent_id/tenant_id 参数', { agent_id: getAgentId(), tenant_id: getTenantId() });
  }
  getAgentId(): string { return getAgentId(); }
  getTenantId(): string { return getTenantId(); }

  // ---------- 联调网关：客户端可发送的消息类型 ----------
  /** send_message：用户上行消息（提交给 main） */
  sendGatewayMessage(payload: unknown): void {
    imLog('会话层', '上行 send_message', { type: 'send_message', payload });
    this.connection.sendFrame(createSendMessageFrame(payload));
  }

  /**
   * v2 发消息：send_message，payload 为 { taskID, contentType [, content, candidateID, humanAction] }。
   * 文本 content 为 string；图片 content 为 object（contentType=102 结构）；
   * 语音 content 为 object（contentType=103）；文件 content 为 object（contentType=105）。
   * AI 候选复审时需带 candidateID + humanAction（approve_original / edit / rewrite / drop）。
   * humanAction=drop 时省略 content（只记审计，不落业务消息）。
   * 注意：WS 回执 send_result 仅表示入队，真正成功以下行 submit_result 为准。
   * 发送前会 waitUntilConnected；连接不可用时抛错。
   */
  async sendMessage(
    taskID: string,
    content: string | object | undefined,
    contentType: 101 | 102 | 103 | 104 | 105 = 101,
    extras?: {
      candidateID?: string;
      humanAction?: 'approve_original' | 'edit' | 'rewrite' | 'drop';
      /** 本地临时 id，便于服务端回显后与乐观气泡配对 */
      clientMsgID?: string;
    },
  ): Promise<void> {
    await this.ensureConnected();
    const payload: Record<string, unknown> = { taskID, contentType };
    // drop：协议要求省略 content；其它场景才带 content
    if (extras?.humanAction !== 'drop') {
      payload.content = content ?? '';
    }
    if (extras?.candidateID) payload.candidateID = extras.candidateID;
    if (extras?.humanAction) payload.humanAction = extras.humanAction;
    if (extras?.clientMsgID) payload.clientMsgID = extras.clientMsgID;
    const frame = createSendMessageFrame(payload);
    imLog('会话层', '上行 send_message（v2）', frame);
    this.connection.sendFrame(frame);
  }
  /** echo_response：用户回传消息，可带 delay_seconds 让服务端延时下发 */
  echoResponse(payload: unknown, delaySeconds?: number): void {
    imLog('会话层', '上行 echo_response', { type: 'echo_response', payload, delay_seconds: delaySeconds });
    this.connection.sendFrame(createEchoResponseFrame(payload, delaySeconds));
  }
  /** ack：确认消费位点 */
  ackSeq(ackSeq: number, cursor?: string): void {
    imLog('会话层', '上行 ack', { type: 'ack', ack_seq: ackSeq, cursor });
    this.connection.sendFrame(createGatewayAckFrame(ackSeq, cursor));
  }
  /** ack 当前已收到的最大 seq（无可确认位点时跳过） */
  ackLatest(cursor?: string): void {
    if (this.lastSeq <= 0) { imWarn('会话层', '暂无可确认的消费位点，跳过 ack'); return; }
    this.ackSeq(this.lastSeq, cursor);
  }
  /** @deprecated v2 网关不支持 resume，断线恢复改走 REST 重拉。保留仅为兼容旧引用。 */
  resume(fromSeq?: number, limit = 200): void {
    const from = fromSeq ?? this.lastSeq + 1;
    imWarn('会话层', 'v2 已废弃 resume（断线恢复请走 REST messages/by_conversation）', { from_seq: from, limit });
    this.connection.sendFrame(createResumeFrame(from, limit));
  }
  /** publish：调试事件发布 */
  publish(eventType: string, payload: unknown): void {
    imLog('会话层', '上行 publish（调试事件发布）', { type: 'publish', event_type: eventType, payload });
    this.connection.sendFrame(createPublishFrame(eventType, payload));
  }

  /** 当前已确认/收到的最大消费位点 */
  getLastSeq(): number { return this.lastSeq; }

  /** 订阅网关下行消息（服务端 message 帧），返回取消订阅函数 */
  onGatewayMessage(listener: (msg: GatewayInboundMessage) => void): () => void {
    gatewayMsgListeners.add(listener);
    return () => gatewayMsgListeners.delete(listener);
  }
  private emitGatewayMessage(msg: GatewayInboundMessage): void {
    for (const l of gatewayMsgListeners) {
      try {
        l(msg);
      } catch (e) {
        imCaptureError('会话层', 'onGatewayMessage 订阅者抛错，已跳过', e);
      }
    }
  }

  /** 订阅 v2 业务下行事件（内层 payload），返回取消订阅函数 */
  onGatewayEvent(listener: (evt: IMGatewayEvent) => void): () => void {
    gatewayEventListeners.add(listener);
    return () => gatewayEventListeners.delete(listener);
  }
  // 单个订阅者抛错不得截断后续订阅者（弹窗/会话缓存同步都挂在这条链上）
  private emitGatewayEvent(evt: IMGatewayEvent): void {
    for (const l of gatewayEventListeners) {
      try {
        l(evt);
      } catch (e) {
        imCaptureError('会话层', 'onGatewayEvent 订阅者抛错，已跳过', e);
      }
    }
  }

  init(): void {
    if (this.initialized) return;
    this.initialized = true;
    // 热更新可能留下旧实例的帧订阅：统一走模块级单槽，避免同帧双打日志/双处理
    frameListenerUnsub?.();
    frameListenerUnsub = this.connection.subscribe((event) => {
      if (event.type === 'frame') this.handleIncomingFrame(event.frame);
    });
    this.connectionUnsub = () => {
      frameListenerUnsub?.();
      frameListenerUnsub = null;
    };
  }

  async start(): Promise<void> {
    if (!this.initialized) this.init();
    const state = this.connection.getState();
    // connection_timeout 时仍允许 start → 走连接层自动/慢重试通路（不再直接拒绝）
    if (state === 'connected' || state === 'connecting' || state === 'reconnecting') {
      imLog('会话层', '连接已建立或进行中，跳过重复 start');
      return;
    }
    if (state === 'connection_timeout') {
      imLog('会话层', '连接处于超时态，改为手动 retry 拉起');
      await this.connection.retry();
      return;
    }
    await this.connection.connect();
  }

  async retry(): Promise<void> {
    if (!this.initialized) this.init();
    await this.connection.retry();
  }
  stop(): void { this.connection.disconnect(); }

  // 注意：不清 gateway 订阅表——它是模块级的，需跨「登出→登录」的实例重建存活
  destroy(): void { this.stop(); this.connectionUnsub?.(); this.connectionUnsub = null; this.connection.destroy(); this.initialized = false; this.lastSeq = 0; this.hasConnectedOnce = false; resetIMStore(); resetIMCache(); resetOutboxQueue(); }

  sendText(conversationId: string, text: string, senderId: string): ChatMessage { return getMessageService().sendText(this.connection, conversationId, text, senderId); }
  sendEmoji(conversationId: string, emojiId: string, fallback: string, senderId: string): ChatMessage { return getMessageService().sendEmoji(this.connection, conversationId, emojiId, fallback, senderId); }
  onStateChange(callback: (state: ConnectionState) => void): () => void { return this.connection.subscribe((event) => { if (event.type === 'state_change') callback(event.state); }); }

  private handleIncomingFrame(frame: any): void {
    if (!frame?.type) return;
    const msg = getMessageService();
    switch (frame.type) {
      // ---- 建连后服务端首帧：payload = { agent_id, connection_id }，v2 无 session_id/resume ----
      case 'connected': {
        // 建连成功日志已由连接层输出，此处只推进状态，避免同帧双打
        this.hasConnectedOnce = true;
        break;
      }
      // ---- 上行确认：send_message / echo_response ----
      case 'send_result': {
        const data = frame.data as SendResultData | undefined;
        imLog('会话层', `收到 send_result（已受理=${data?.received ?? '?'}，队列长度=${data?.queue_length ?? '?'}）`, data);
        break;
      }
      // ---- 位点确认结果 ----
      case 'ack_result': {
        const data = frame.data as AckResultData | undefined;
        imLog('会话层', `收到 ack_result（更新=${data?.ack_updated ?? '?'}，ack_seq=${data?.ack_seq ?? '?'}）`, data);
        break;
      }
      // ---- 断线补拉结果 ----
      case 'resume_result': {
        const data = frame.data as ResumeResultData | undefined;
        imLog('会话层', `收到 resume_result（会话存在=${data?.session_found ?? '?'}，需全量同步=${data?.need_full_sync ?? '?'}，next_seq=${data?.next_seq ?? '?'}，事件数=${data?.events?.length ?? 0}）`, data);
        if (data?.need_full_sync) imWarn('会话层', '服务端要求全量同步（need_full_sync=true），位点可能已过期');
        if (Array.isArray(data?.events)) data.events.forEach((evt) => this.handleResumeEvent(evt));
        if (typeof data?.next_seq === 'number' && data.next_seq - 1 > this.lastSeq) this.lastSeq = data.next_seq - 1;
        break;
      }
      // ---- 调试事件发布结果 ----
      case 'publish_result': {
        const data = frame.data as PublishResultData | undefined;
        imLog('会话层', `收到 publish_result（接受=${data?.accepted ?? '?'}，seq=${data?.seq ?? '?'}）`, data);
        if (typeof data?.seq === 'number') this.trackSeq(data.seq);
        break;
      }
      // ---- 不支持类型等错误 ----
      case 'error': imWarn('会话层', `收到 error：${frame.code ?? 'unknown'}`, { code: frame.code, message: frame.message }); break;
      // ---- v2：业务下行统一外层 message，内层 payload.type 决定业务 ----
      case 'message': {
        this.handleGatewayMessage(frame);
        break;
      }
      // ---- 既有 IM 同步结果 ----
      case 'sync_result': msg.handleSyncResult(frame.payload as SyncResultPayload); break;
    }
  }

  /**
   * v2 业务下行分发：外层固定为 message，业务类型在 payload.type。
   * 统一广播给 onGatewayEvent 订阅者；annotation_event 额外兼容旧的 onGatewayMessage(text)。
   */
  private handleGatewayMessage(frame: any): void {
    const inner = (frame?.payload ?? frame?.data) as IMGatewayEvent | undefined;
    const innerType = (inner as { type?: string })?.type;
    if (!inner || !innerType) {
      imWarn('会话层', '收到 message 但缺少内层 payload.type，已忽略', frame);
      return;
    }
    imLog('会话层', `收到业务下行 payload.type=${innerType}`, inner);
    this.emitGatewayEvent(inner);

    // 兼容旧订阅：annotation_event 提取可展示文本广播给 onGatewayMessage
    if (innerType === 'annotation_event') {
      const message = (inner as { event?: { message?: { content?: string; serverMsgID?: string } } }).event?.message;
      const text = parseApiMessageContent(message?.content) || extractText(inner);
      if (text) this.emitGatewayMessage({ text, raw: inner, receivedAt: Date.now() });
    }
  }

  /** 处理 resume 补拉回来的单条事件，并推进位点 */
  private handleResumeEvent(evt: unknown): void {
    imLog('会话层', 'resume 补拉事件', evt);
    this.trackSeq(extractSeq(evt));
  }

  /** 推进已收到的最大消费位点 */
  private trackSeq(seq?: number): void {
    if (typeof seq === 'number' && seq > this.lastSeq) this.lastSeq = seq;
  }
}

// ============================================================
// 服务端下发体解析（模块级纯函数，便于热更新且不依赖实例）
// ============================================================

/** 从任意服务端下发体里尽力提取 seq */
function extractSeq(body: unknown): number | undefined {
  if (body && typeof body === 'object') {
    const seq = (body as { seq?: unknown }).seq;
    if (typeof seq === 'number') return seq;
  }
  return undefined;
}

/**
 * 从服务端下发体里尽力提取可展示文本，兼容多层嵌套结构。
 * 例如 { type:"message", message:{ echo:"正在" } } -> "正在"
 */
function extractText(body: unknown, depth = 0): string {
  if (body == null) return '';
  if (typeof body === 'string') return body;
  if (depth < 5 && typeof body === 'object') {
    const o = body as Record<string, unknown>;
    // 优先取常见文本字段（字符串直接返回）
    for (const key of ['text', 'echo', 'content'] as const) {
      if (typeof o[key] === 'string') return o[key] as string;
    }
    // message 可能是字符串，也可能是对象（继续下钻）
    if (typeof o.message === 'string') return o.message;
    // 继续在常见容器字段里下钻
    for (const key of ['message', 'payload', 'data'] as const) {
      if (o[key] && typeof o[key] === 'object') {
        const nested = extractText(o[key], depth + 1);
        if (nested) return nested;
      }
    }
  }
  return '';
}

let _chatService: ChatService | null = null;
export function getChatService(): ChatService { if (!_chatService) _chatService = new ChatService(); return _chatService; }
export function resetChatService(): void { _chatService?.destroy(); _chatService = null; }
export default getChatService;
