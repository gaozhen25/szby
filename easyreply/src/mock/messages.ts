// ============================================================
// 聊天详情 Mock 消息
// ============================================================

export type MockMessageRole = 'user' | 'agent';

export interface MockChatMessage {
  id: string;
  role: MockMessageRole;
  content: string;
  time: string;
  timeLabel?: string;
  showTimeLabel?: boolean;
  quote?: {
    sender: string;
    content: string;
  };
}

export const MOCK_CHAT_MESSAGES: Record<string, MockChatMessage[]> = {
  '1': [
    {
      id: 'm1',
      role: 'user',
      content: '你好，在吗？',
      time: '10:20',
      showTimeLabel: true,
      timeLabel: '5月30日 10:20',
    },
    {
      id: 'm2',
      role: 'agent',
      content: '在的，请问有什么可以帮您？',
      time: '10:21',
    },
    {
      id: 'm3',
      role: 'user',
      content: '你不想理我就算了',
      time: '10:25',
      showTimeLabel: true,
      timeLabel: '5月30日 10:25',
      quote: {
        sender: '客服',
        content: '在的，请问有什么可以帮您？',
      },
    },
    {
      id: 'm4',
      role: 'agent',
      content: '抱歉让您久等了，我再帮您看看～',
      time: '10:26',
    },
  ],
  default: [
    {
      id: 'd1',
      role: 'user',
      content: '你好',
      time: '09:00',
      showTimeLabel: true,
      timeLabel: '今天 09:00',
    },
    {
      id: 'd2',
      role: 'agent',
      content: '您好，很高兴为您服务。',
      time: '09:01',
    },
  ],
};

export function getMockMessages(conversationId: string): MockChatMessage[] {
  return MOCK_CHAT_MESSAGES[conversationId] ?? MOCK_CHAT_MESSAGES.default;
}
