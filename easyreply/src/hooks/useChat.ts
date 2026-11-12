import { useCallback, useReducer, useEffect, useSyncExternalStore } from 'react';
import { getChatService, getIMStore } from '@/core/im';
import type { ChatMessage, ConnectionState, Conversation } from '@/core/im';

export function useIMConnection() {
  const chat = getChatService(); const [, f] = useReducer((n: number) => n + 1, 0);
  useEffect(() => {
    const conn = chat.getConnection();
    if (!conn) return;
    return conn.subscribe(() => f());
  }, [chat]);
  return {
    state: chat.getConnection()?.getState() ?? 'disconnected' as ConnectionState,
    isOnline: chat.getConnection()?.isOnline() ?? true,
    isConfigured: chat.isWsConfigured(), wsUrl: chat.getWsUrl(),
    connect: () => chat.start(),
    retry: () => chat.retry(),
    disconnect: () => chat.stop(),
  };
}

export function useConversations(): Conversation[] {
  const [, f] = useReducer((n: number) => n + 1, 0);
  const store = getIMStore();
  useEffect(() => { const t = setInterval(f, 2000); return () => clearInterval(t); }, []);
  return store.getConversations();
}

export function useChatMessages(conversationId: string | undefined) {
  const chat = getChatService(); const store = getIMStore(); const [, f] = useReducer((n: number) => n + 1, 0);
  useEffect(() => chat.onStateChange(() => f()), [chat]);
  const messages = conversationId ? store.getMessages(conversationId) : [];
  const connectionState = chat.getConnection()?.getState() ?? 'disconnected' as ConnectionState;
  return {
    messages, connectionState,
    sendText: (text: string, senderId: string) => { if (conversationId) chat.sendText(conversationId, text, senderId); },
    markRead: () => { if (conversationId) console.log('[useChat] markRead'); },
    loadMore: async () => { if (conversationId) console.log('[useChat] loadMore'); },
  };
}

export function useChat(conversationId?: string) {
  const c = useIMConnection(); const convs = useConversations(); const msgs = useChatMessages(conversationId);
  return { ...c, conversations: convs, ...msgs, configureWsUrl: (url: string) => getChatService().configureWsUrl(url) };
}
export default useChat;
