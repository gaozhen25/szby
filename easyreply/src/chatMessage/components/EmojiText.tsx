import { Image, StyleSheet, Text, View } from 'react-native';
import { isPureWechatEmojiText, parseWechatEmojiText } from '@/core/im/wechat-emoji';
import { getWechatEmojiUri } from '@/chatMessage/message/chat-emoji-draft';
import { ChatType } from '@/design/chat-type';

export type EmojiTextVariant = 'bubble' | 'preview';

type Props = {
  text: string;
  color: string;
  textStyle?: object;
  /** bubble：聊天气泡；preview：会话列表末条，单行 */
  variant?: EmojiTextVariant;
};

function renderSegments(
  text: string,
  color: string,
  textStyle: object | undefined,
  emojiStyle: object,
  textBase: object,
) {
  const segments = parseWechatEmojiText(text);
  return segments.map((seg, index) => {
    if (seg.kind !== 'emoji') {
      return (
        <Text key={`text-${index}`} style={[textBase, textStyle, { color }]}>
          {seg.value}
        </Text>
      );
    }
    const uri = getWechatEmojiUri(seg.name);
    if (!uri) {
      return (
        <Text key={`text-${index}`} style={[textBase, textStyle, { color }]}>
          [{seg.name}]
        </Text>
      );
    }
    return (
      <Image
        key={`emoji-${index}`}
        source={{ uri }}
        style={emojiStyle}
        resizeMode="contain"
      />
    );
  });
}

/** 将 [大哭] 等微信文本表情渲染为本地图片，其余按普通文本展示 */
export function EmojiText({ text, color, textStyle, variant = 'bubble' }: Props) {
  if (variant === 'preview') {
    const segments = parseWechatEmojiText(text);
    if (!segments.some((s) => s.kind === 'emoji')) {
      return (
        <Text numberOfLines={1} ellipsizeMode="tail" style={[styles.previewText, textStyle, { color }]}>
          {text}
        </Text>
      );
    }
    return (
      <Text numberOfLines={1} ellipsizeMode="tail" style={[styles.previewText, textStyle, { color }]}>
        {renderSegments(text, color, textStyle, styles.previewEmoji, styles.previewText)}
      </Text>
    );
  }

  if (isPureWechatEmojiText(text)) {
    const name = text.trim().slice(1, -1);
    const uri = getWechatEmojiUri(name);
    if (uri) {
      return <Image source={{ uri }} style={styles.pureEmoji} resizeMode="contain" />;
    }
  }

  const segments = parseWechatEmojiText(text);
  if (!segments.some((s) => s.kind === 'emoji')) {
    return <Text style={[styles.text, textStyle, { color }]}>{text}</Text>;
  }

  return (
    <View style={styles.inlineRow}>
      {renderSegments(text, color, textStyle, styles.inlineEmoji, styles.text)}
    </View>
  );
}

const styles = StyleSheet.create({
  text: {
    fontSize: ChatType.size.bubble,
    lineHeight: ChatType.lineHeight.bubble,
    fontWeight: ChatType.weight.regular,
  },
  pureEmoji: {
    width: ChatType.size.pureEmoji,
    height: ChatType.size.pureEmoji,
  },
  inlineRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
  },
  inlineEmoji: {
    width: ChatType.size.bubbleEmoji,
    height: ChatType.size.bubbleEmoji,
    marginHorizontal: 1,
  },
  previewText: {
    fontSize: ChatType.size.subLabel,
    lineHeight: ChatType.lineHeight.subLabel,
    fontWeight: ChatType.weight.regular,
  },
  previewEmoji: {
    width: ChatType.size.previewEmoji,
    height: ChatType.size.previewEmoji,
    marginHorizontal: 1,
  },
});
