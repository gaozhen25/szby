import { fetchConversations } from '@/api/im';
import { getIMCache } from './store/im-cache';
import { getIMStore } from './store/im-store';
import { getMessagePreview } from './utils';
import type { ChatMessage, Conversation } from './types';

export class SessionService {
  async loadConversations(): Promise<Conversation[]> {
    const store = getIMStore(); const cache = getIMCache();
    const cached = await cache.loadConversations(); if (cached.length > 0) store.setConversations(cached);
    const remote = await fetchConversations(); if (remote.length > 0) { store.setConversations(remote); await cache.saveConversations(remote); }
    return store.getConversations();
  }

  onNewMessage(message: ChatMessage): void {
    const store = getIMStore(); const existing = store.getConversation(message.conversationId);
    const preview = getMessagePreview(message);
    const patch: Partial<Conversation> = { lastMessagePreview: preview, lastMessageAt: message.createdAt, updatedAt: Date.now() };
    if (message.senderRole !== 'user' && message.readStatus === 'unread') patch.unreadCount = (existing?.unreadCount ?? 0) + 1;
    if (existing) store.updateConversation(message.conversationId, patch);
    else store.upsertConversation({ id: message.conversationId, unreadCount: patch.unreadCount ?? 0, updatedAt: Date.now(), ...patch } as Conversation);
    void this.persistConversations();
  }

  markRead(conversationId: string): void { const store = getIMStore(); store.updateConversation(conversationId, { unreadCount: 0 }); void this.persistConversations(); }

  private async persistConversations(): Promise<void> { const convs = getIMStore().getConversations(); await getIMCache().saveConversations(convs); }
}

let _sessionService: SessionService | null = null;
export function getSessionService(): SessionService { if (!_sessionService) _sessionService = new SessionService(); return _sessionService; }
export default getSessionService;
