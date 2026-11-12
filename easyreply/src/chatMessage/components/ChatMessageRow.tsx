// ============================================================
// 聊天气泡（微信风格 · 浅色 · 带小三角）
// 消息区背景透明，沿用 ScreenCanvas 统一背景
// ============================================================
import { StyleSheet, Text, View } from 'react-native';

import { useTheme } from '@/design/theme-context';
import { Tokens } from '@/design/tokens';
import type { MockChatMessage } from '@/mock/messages';

/** 发送气泡：微信绿 */
const SENT_BUBBLE = '#95EC69';

function BubbleTail({ side, color }: { side: 'left' | 'right'; color: string }) {
  const isLeft = side === 'left';
  return (
    <View
      style={[
        styles.tail,
        isLeft ? styles.tailLeft : styles.tailRight,
        isLeft ? { borderRightColor: color } : { borderLeftColor: color },
      ]}
    />
  );
}

function QuoteBlock({
  quote,
  isAgent,
}: {
  quote: NonNullable<MockChatMessage['quote']>;
  isAgent: boolean;
}) {
  return (
    <View style={[styles.quoteBox, isAgent ? styles.quoteAgent : styles.quoteUser]}>
      <Text style={styles.quoteName} numberOfLines={1}>
        {quote.sender}
      </Text>
      <Text style={styles.quoteText} numberOfLines={2}>
        {quote.content}
      </Text>
    </View>
  );
}

export function ChatTimeLabel({ label }: { label: string }) {
  const theme = useTheme();
  return (
    <View style={styles.timeWrap}>
      <Text style={[styles.timeLabel, { color: theme.textSubtle }]}>{label}</Text>
    </View>
  );
}

export function ChatMessageRow({
  message,
  avatarColor,
  compact,
}: {
  message: MockChatMessage;
  avatarColor: string;
  compact?: boolean;
}) {
  const theme = useTheme();
  const isAgent = message.role === 'agent';
  const bubbleColor = isAgent ? SENT_BUBBLE : theme.surface;

  const avatar = (
    <View
      style={[
        styles.avatar,
        { backgroundColor: isAgent ? theme.primary : avatarColor },
      ]}
    />
  );

  const bubbleBody = (
    <>
      {message.quote && !isAgent ? (
        <QuoteBlock quote={message.quote} isAgent={false} />
      ) : null}
      <Text style={[styles.bubbleText, { color: theme.text }]}>
        {message.content}
      </Text>
      {message.quote && isAgent ? (
        <QuoteBlock quote={message.quote} isAgent />
      ) : null}
    </>
  );

  return (
    <View
      style={[
        styles.row,
        isAgent ? styles.rowAgent : styles.rowUser,
        compact ? styles.gapCompact : styles.gapNormal,
      ]}
    >
      {!isAgent ? avatar : null}

      <View style={[styles.body, isAgent ? styles.bodyAgent : styles.bodyUser]}>
        {!isAgent ? <BubbleTail side="left" color={bubbleColor} /> : null}
        <View
          style={[
            styles.bubble,
            isAgent
              ? { backgroundColor: SENT_BUBBLE }
              : {
                  backgroundColor: theme.surface,
                  borderColor: theme.border,
                  borderWidth: StyleSheet.hairlineWidth,
                },
            isAgent ? styles.bubbleAgent : styles.bubbleUser,
            Tokens.shadow.card,
          ]}
        >
          {bubbleBody}
        </View>
        {isAgent ? <BubbleTail side="right" color={bubbleColor} /> : null}
      </View>

      {isAgent ? avatar : null}
    </View>
  );
}

const styles = StyleSheet.create({
  timeWrap: {
    alignItems: 'center',
    paddingVertical: 10,
  },
  timeLabel: {
    fontSize: 12,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    paddingHorizontal: 12,
  },
  rowUser: {
    justifyContent: 'flex-start',
  },
  rowAgent: {
    justifyContent: 'flex-end',
  },
  gapCompact: {
    marginBottom: 8,
  },
  gapNormal: {
    marginBottom: 14,
  },
  avatar: {
    width: 40,
    height: 40,
    borderRadius: 4,
  },
  body: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    maxWidth: '72%',
  },
  bodyUser: {
    marginLeft: 8,
  },
  bodyAgent: {
    marginRight: 8,
  },
  tail: {
    width: 0,
    height: 0,
    marginTop: 12,
    borderTopWidth: 5,
    borderBottomWidth: 5,
    borderTopColor: 'transparent',
    borderBottomColor: 'transparent',
  },
  tailLeft: {
    borderRightWidth: 6,
    marginRight: -1,
  },
  tailRight: {
    borderLeftWidth: 6,
    marginLeft: -1,
  },
  bubble: {
    paddingHorizontal: 12,
    paddingVertical: 10,
    minHeight: 40,
    justifyContent: 'center',
  },
  bubbleUser: {
    borderTopLeftRadius: 2,
    borderTopRightRadius: 8,
    borderBottomLeftRadius: 8,
    borderBottomRightRadius: 8,
  },
  bubbleAgent: {
    borderTopLeftRadius: 8,
    borderTopRightRadius: 2,
    borderBottomLeftRadius: 8,
    borderBottomRightRadius: 8,
  },
  bubbleText: {
    fontSize: 16,
    lineHeight: 22,
  },
  quoteBox: {
    borderRadius: 4,
    paddingHorizontal: 8,
    paddingVertical: 6,
  },
  quoteUser: {
    backgroundColor: 'rgba(0,0,0,0.04)',
    marginBottom: 8,
  },
  quoteAgent: {
    backgroundColor: 'rgba(0,0,0,0.06)',
    marginTop: 8,
  },
  quoteName: {
    fontSize: 12,
    color: '#888',
    marginBottom: 2,
  },
  quoteText: {
    fontSize: 13,
    color: '#666',
    lineHeight: 18,
  },
});
