export { getImWsUrl, setImWsUrl, clearImWsUrlOverride, isImWsUrlConfigured, buildImWsUrl, getAgentId, setAgentId, getTenantId, setTenantId, resetAgentIdentity, getSessionId, setSessionId } from './config';
export { IMConnection, getIMConnection, resetIMConnection } from './connection';
export {
  getWsKeepaliveProfile,
  decideKeepaliveOnResume,
  getNetworkRestoreDelayMs,
  isPostSuspendRecoveryReason,
  hasHitHardReconnectLimit,
  shouldEnterSoftTimeout,
  shouldPauseHeartbeatWhileHidden,
  resolveNetworkFingerprint,
  WS_READY_OPEN,
} from './ws-keepalive';
export type {
  WsKeepaliveProfile,
  KeepaliveResumeAction,
  KeepaliveResumeInput,
  NetworkFingerprintInput,
} from './ws-keepalive';
export { ChatService, getChatService, resetChatService } from './chat-service';
export { getMessageService } from './message-service';
export { getSessionService } from './session-service';
export { getSyncService } from './sync';
export { getOutboxQueue } from './outbox';
export { getIMStore, resetIMStore } from './store/im-store';
export { getIMCache, setIMCache, resetIMCache } from './store/im-cache';
export type { IMCache } from './store/im-cache';
export { createTransport } from './transport';
export type { IMTransport, TransportEvent } from './transport';
export { decodeFrame, encodeFrame, createAuthFrame, createMessageFrame, createReadFrame, createSyncFrame, parseIncomingMessage, createPingFrame, createPongFrame, createSendMessageFrame, createEchoResponseFrame, createGatewayAckFrame, createResumeFrame, createPublishFrame } from './protocol';
export { generateClientMsgId, getMessagePreview, generateSessionId, imLog, imWarn, imCaptureError, parseApiMessageContent, normalizeSendTimeMs, normalizeServerMessage, normalizeServerMessages, isOutgoingServerMessage, formatLastMessagePreview, getTaskSessionInfo, getTaskLastMessage, previewFromServerMessage, preserveServerMessageForCache, withTaskLastMessage, detectChatPlatform, resolveAudienceApiPlatform } from './utils';
export { initIM, startIM, stopIM } from './init';
// StartIMOptions not exported separately from './init';
export type { ConnectionState, MessageStatus, MessageType, SenderRole, ReadStatus, IMFrameType, ChatMessage, Conversation, OutboxItem, IMFrame, AckPayload, ReadPayload, SyncPayload, SyncResultPayload, IMConnectionOptions, IMConnectionEvent, IMConnectionListener, ConnectedFrameData, SendResultData, AckResultData, ResumeResultData, PublishResultData, GatewayInboundMessage } from './types';
export type {
  TaskStatus, TaskMode, IMTask, IMTaskSession, IMServerMessage, IMTaskContext, MessageDirection,
  IMActionResultType, IMGatewayEventType, IMGatewayEvent,
  IMAnnotationEventPayload, IMAiReviewRequiredPayload, IMAnnotationTaskClaimedPayload, IMTransferReportedPayload, IMOwnershipChangedPayload,
  IMSubmitResultPayload, IMActionResultPayload,
  AdoptionContext, AdoptionCandidate, AdoptionHumanAction, AdoptionStatus, ProactiveActionHint,
} from './types';
/** AnnotationTaskSource 常量枚举 + 同名类型；ANNOTATION_TASK_SOURCE_LABEL 数值→含义 */
export { AnnotationTaskSource, ANNOTATION_TASK_SOURCE_LABEL } from './types';
