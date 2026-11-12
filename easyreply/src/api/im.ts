import { get } from '@/lib/http';
import type { ChatMessage, Conversation } from '@/core/im/types';

export async function fetchConversations(): Promise<Conversation[]> {
  const res = await get<{ data: Conversation[] }>('/api/conversations');
  return (res.data as any)?.data ?? res.data ?? [];
}

export async function fetchMessages(conversationId: string, params?: { beforeSeq?: number; limit?: number }): Promise<ChatMessage[]> {
  const res = await get<{ data: ChatMessage[] }>(`/api/conversations/${conversationId}/messages`, params as any);
  return (res.data as any)?.data ?? res.data ?? [];
}

export async function fetchMessagesSince(conversationId: string, lastSeq: any): Promise<ChatMessage[]> {
  const res = await get<{ data: ChatMessage[] }>(`/api/conversations/${conversationId}/messages/since`, { lastSeq });
  return (res.data as any)?.data ?? res.data ?? [];
}

export async function uploadChatMedia(params: { uri: string; name: string; type: string }): Promise<{ url: string }> {
  const { uploadImageAsset } = await import('@/api/assets');
  const res = await uploadImageAsset({
    uri: params.uri,
    fileName: params.name,
    mimeType: params.type,
  });
  return { url: res.url };
}
