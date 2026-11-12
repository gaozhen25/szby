import { fetchMessages, uploadChatMedia } from '@/api/im';
import type { IMConnection } from './connection';
import { getOutboxQueue } from './outbox';
import { createMessageFrame, createReadFrame } from './protocol';
import { getSessionService } from './session-service';
import { getIMCache } from './store/im-cache';
import { getIMStore } from './store/im-store';
import type { AckPayload, AudioContent, ChatMessage, ImageContent, MessageContent, MessageType, ReadPayload, SyncResultPayload, TextContent } from './types';
import { generateClientMsgId } from './utils';

export class MessageService {
  handleIncoming(message: ChatMessage): void {
    const store = getIMStore(); store.upsertMessage(message);
    getSessionService().onNewMessage(message);
    void this.persistMessages(message.conversationId);
  }

  handleAck(payload: AckPayload): void {
    const store = getIMStore();
    store.updateMessage(payload.clientMsgId, { status: 'sent', serverMsgId: payload.serverMsgId, seq: payload.seq });
    getOutboxQueue().handleAck(payload);
    void this.persistMessages(payload.conversationId);
  }

  handleSyncResult(payload: SyncResultPayload): void {
    getIMStore().upsertMessages(payload.conversationId, payload.messages);
    void this.persistMessages(payload.conversationId);
  }

  sendText(connection: IMConnection, conversationId: string, text: string, senderId: string): ChatMessage {
    return this.send(connection, conversationId, 'text', { text }, senderId, 'user');
  }

  sendEmoji(connection: IMConnection, conversationId: string, emojiId: string, fallback: string, senderId: string): ChatMessage {
    return this.send(connection, conversationId, 'emoji', { emojiId, fallback }, senderId, 'user');
  }

  async sendImage(connection: IMConnection, conversationId: string, localUri: string, senderId: string, fileName = 'image.jpg'): Promise<ChatMessage> {
    const message = this.createLocal(conversationId, 'image', { url: localUri }, senderId, 'user');
    getIMStore().upsertMessage(message);
    try {
      const { url } = await uploadChatMedia({ uri: localUri, name: fileName, type: 'image/jpeg' });
      getIMStore().updateMessage(message.clientMsgId, { content: { url } });
      this.dispatchSend(connection, message, { url }); return message;
    } catch { getIMStore().updateMessage(message.clientMsgId, { status: 'failed' }); getOutboxQueue().markFailed(message.clientMsgId); throw new Error('[IM] image upload failed'); }
  }

  async sendAudio(connection: IMConnection, conversationId: string, localUri: string, duration: number, senderId: string, fileName = 'audio.m4a'): Promise<ChatMessage> {
    const message = this.createLocal(conversationId, 'audio', { url: localUri, duration }, senderId, 'user');
    getIMStore().upsertMessage(message);
    try {
      const { url } = await uploadChatMedia({ uri: localUri, name: fileName, type: 'audio/m4a' });
      getIMStore().updateMessage(message.clientMsgId, { content: { url, duration } });
      this.dispatchSend(connection, message, { url, duration }); return message;
    } catch { getIMStore().updateMessage(message.clientMsgId, { status: 'failed' }); getOutboxQueue().markFailed(message.clientMsgId); throw new Error('[IM] audio upload failed'); }
  }

  sendReadReceipt(connection: IMConnection, payload: ReadPayload): void {
    getSessionService().markRead(payload.conversationId);
    const store = getIMStore();
    store.getMessages(payload.conversationId).forEach((msg) => {
      if (msg.seq && msg.seq <= payload.readUpToSeq && msg.readStatus === 'unread') store.updateMessage(msg.clientMsgId, { readStatus: 'read' });
    });
    if (connection.getState() === 'connected') { try { connection.sendFrame(createReadFrame(payload)); } catch { /* non-critical */ } }
  }

  async loadMoreMessages(conversationId: string): Promise<ChatMessage[]> {
    const store = getIMStore(); const existing = store.getMessages(conversationId);
    const firstSeq = existing.length > 0 ? Math.min(...existing.map((m) => m.seq ?? Infinity)) : undefined;
    const older = await fetchMessages(conversationId, { beforeSeq: firstSeq === Infinity ? undefined : firstSeq, limit: 20 });
    if (older.length > 0) { store.upsertMessages(conversationId, older); await this.persistMessages(conversationId); }
    return older;
  }

  onSendFailed(clientMsgId: string, conversationId: string): void { getIMStore().updateMessage(clientMsgId, { status: 'failed' }); void this.persistMessages(conversationId); }

  private send(connection: IMConnection, conversationId: string, type: MessageType, content: MessageContent, senderId: string, senderRole: ChatMessage['senderRole']): ChatMessage {
    const message = this.createLocal(conversationId, type, content, senderId, senderRole);
    getIMStore().upsertMessage(message); this.dispatchSend(connection, message, content);
    void this.persistMessages(conversationId); return message;
  }

  private createLocal(conversationId: string, type: MessageType, content: MessageContent, senderId: string, senderRole: ChatMessage['senderRole']): ChatMessage {
    return { clientMsgId: generateClientMsgId(), conversationId, senderId, senderRole, type, content, status: 'sending', readStatus: 'read', createdAt: Date.now() };
  }

  private dispatchSend(connection: IMConnection, message: ChatMessage, content: MessageContent): void {
    const frame = createMessageFrame(message.conversationId, message.clientMsgId, { type: message.type, content, senderId: message.senderId, senderRole: message.senderRole, createdAt: message.createdAt });
    getOutboxQueue().enqueue(connection, { clientMsgId: message.clientMsgId, conversationId: message.conversationId, frame });
  }

  private async persistMessages(conversationId: string): Promise<void> {
    const messages = getIMStore().getMessages(conversationId);
    await getIMCache().saveMessages(conversationId, messages);
  }
}

let _messageService: MessageService | null = null;
export function getMessageService(): MessageService { if (!_messageService) _messageService = new MessageService(); return _messageService; }
export default getMessageService;
