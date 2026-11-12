import { getRole } from '@/core/auth';
import type { MockConversation } from '@/mock/data';
import { prefetchChatMessagesToMemory } from '@/chatMessage/message/chat-messages-cache';

/** 进房路由参数。空字符串表示清除上一次残留的旁观字段。 */
export type ConversationChatRouteParams = {
  id: string;
  supervisor: string;
  annotatorId: string;
};

/**
 * 会话列表进房参数。
 * 主管点非自持活跃会话时与标注员列表一致：旁观进房（supervisor=1）。
 * 自持且活跃仍走客服视角，可发送。
 */
export function conversationChatRouteParams(item: MockConversation): ConversationChatRouteParams {
  const ownedAndActive =
    !item.inactive && !item.returnedToAgent && !item.supervisorTakeover;
  const browse = getRole() === 'supervisor' && !ownedAndActive;
  if (!browse) {
    return { id: item.id, supervisor: '', annotatorId: '' };
  }
  return {
    id: item.id,
    supervisor: '1',
    annotatorId: item.fromAgentId?.trim() || '',
  };
}

/** 列表点进聊天前预温消息缓存（Web / 移动端共用） */
export function prefetchConversationChatCache(item: MockConversation): void {
  const im = item.imConversationID?.trim();
  if (im) prefetchChatMessagesToMemory(im);
}
