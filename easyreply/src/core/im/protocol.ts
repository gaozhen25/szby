// ============================================================
// IM 协议层
// ============================================================
import type { IMFrame, IMFrameType, ReadPayload, SyncPayload, ChatMessage } from './types';
import { generateRequestId } from './utils';

export function decodeFrame(raw: string): IMFrame | null {
  try {
    const data = JSON.parse(raw) as Partial<IMFrame>;
    // 联调网关消息不带 timestamp（仅有 type/data/ts 等），因此只校验 type
    if (!data || typeof data.type !== 'string') return null;
    return data as IMFrame;
  } catch { return null; }
}

export function encodeFrame(frame: IMFrame): string { return JSON.stringify(frame); }

function createFrame(type: IMFrameType, payload?: unknown, extra?: Partial<IMFrame>): IMFrame {
  return { type, timestamp: Date.now(), requestId: generateRequestId(), ...extra, payload };
}

export function createAuthFrame(token: string): IMFrame { return createFrame('auth', { token }); }

// ============================================================
// 联调网关上行帧（/ws/events）—— 严格按网关约定的最小报文构造
// ============================================================

/** 心跳：{ "type": "ping", "payload": "abc123" } */
export function createPingFrame(payload?: string): IMFrame {
  return { type: 'ping', payload: payload ?? generateRequestId() };
}

/** 回应服务端 ping（兜底，网关通常由服务端回 pong） */
export function createPongFrame(payload?: string): IMFrame {
  return { type: 'pong', payload, ts: Date.now() };
}

/** 用户上行消息：{ "type": "send_message", "payload": { "text": "hello" } } */
export function createSendMessageFrame(payload: unknown): IMFrame {
  return { type: 'send_message', payload };
}

/**
 * 回声/应答模式回传：{ "type": "echo_response", "payload": { ... }, "delay_seconds": 2 }
 * delay_seconds 为顶层字段（非 payload 内），表示服务端延时下发的秒数
 */
export function createEchoResponseFrame(payload: unknown, delaySeconds?: number): IMFrame {
  const frame: IMFrame = { type: 'echo_response', payload };
  if (typeof delaySeconds === 'number') frame.delay_seconds = delaySeconds;
  return frame;
}

/** 确认消费位点：{ "type": "ack", "ack_seq": 12, "cursor": "c12" } */
export function createGatewayAckFrame(ackSeq: number, cursor?: string): IMFrame {
  return { type: 'ack', ack_seq: ackSeq, cursor };
}

/** 断线恢复补拉历史：{ "type": "resume", "from_seq": 1, "limit": 200 } */
export function createResumeFrame(fromSeq: number, limit = 200): IMFrame {
  return { type: 'resume', from_seq: fromSeq, limit };
}

/** 调试事件发布：{ "type": "publish", "event_type": "message", "payload": { "k": 1 } } */
export function createPublishFrame(eventType: string, payload: unknown): IMFrame {
  return { type: 'publish', event_type: eventType, payload };
}

export function createMessageFrame(conversationId: string, clientMsgId: string, payload: unknown): IMFrame {
  return createFrame('message', payload, { conversationId, clientMsgId });
}

export function createReadFrame(payload: ReadPayload): IMFrame {
  return createFrame('read', payload, { conversationId: payload.conversationId });
}

export function createSyncFrame(payload: SyncPayload): IMFrame {
  return createFrame('sync', payload, { conversationId: payload.conversationId });
}

export function parseIncomingMessage(frame: IMFrame): ChatMessage | null {
  if (frame.type !== 'message' || !frame.conversationId || !frame.payload) return null;
  const payload = frame.payload as Partial<ChatMessage>;
  if (!payload.senderId || !payload.type || !payload.content) return null;
  return {
    clientMsgId: frame.clientMsgId ?? payload.clientMsgId ?? frame.serverMsgId ?? '',
    serverMsgId: frame.serverMsgId ?? payload.serverMsgId,
    conversationId: frame.conversationId, senderId: payload.senderId,
    senderRole: payload.senderRole ?? 'agent', type: payload.type,
    content: payload.content, status: 'sent',
    readStatus: payload.readStatus ?? 'unread', seq: payload.seq,
    createdAt: payload.createdAt ?? frame.timestamp ?? Date.now(), extra: payload.extra,
  };
}

export default {
  decodeFrame, encodeFrame, createAuthFrame, createPingFrame, createPongFrame,
  createMessageFrame, createReadFrame, createSyncFrame, parseIncomingMessage,
  createSendMessageFrame, createEchoResponseFrame, createGatewayAckFrame, createResumeFrame, createPublishFrame,
};
