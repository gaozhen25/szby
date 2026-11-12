// ============================================================
// 聊天列表项构建
// ============================================================
import type { MockChatMessage } from '@/mock/messages';

export type ChatListItem =
  | { type: 'time'; id: string; label: string }
  | {
      type: 'message';
      id: string;
      message: MockChatMessage;
      compact: boolean;
    };

export function buildChatListItems(messages: MockChatMessage[]): ChatListItem[] {
  const items: ChatListItem[] = [];
  let prev: MockChatMessage | undefined;

  for (const message of messages) {
    if (message.showTimeLabel && message.timeLabel) {
      items.push({ type: 'time', id: `time-${message.id}`, label: message.timeLabel });
    }

    const compact = !!prev && prev.role === message.role && !message.showTimeLabel;

    items.push({ type: 'message', id: message.id, message, compact });
    prev = message;
  }

  return items;
}
