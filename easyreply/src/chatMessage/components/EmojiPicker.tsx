// ============================================================
// 微信文本表情选择面板：资源来自 WECHAT_EMOJI_SOURCES
// 点击回调表情名（不含中括号），由调用方拼成 [名称] 填入输入框
// 与 ChatComposer 一致：用 resolveAssetSource URI 加载（require 直传 Image 在 iOS 上会空白）
// ============================================================
import { memo, useMemo } from 'react';
import { Image, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { RollbackOutlined, SendOutlined } from '@/ui/antd-icons';
import { WECHAT_EMOJI_SOURCES } from '@/core/im/wechat-emoji';
import { getWechatEmojiUri } from '@/chatMessage/message/chat-emoji-draft';

const PANEL_HEIGHT = 260;
/** 浮动按钮高度 + 上下留白，用于列表底部预留空间 */
const ACTION_RESERVED_SPACE = 58;

type Props = {
  onSelect: (name: string) => void;
  onDelete: () => void;
  onSend: () => void;
  canSend: boolean;
  /** 嵌在带 tab 的面板内时撑满父级，不再使用固定高度 */
  fill?: boolean;
  backgroundColor?: string;
  borderColor?: string;
  primaryColor?: string;
  iconColor?: string;
  disabledColor?: string;
};

export const EmojiPicker = memo(function EmojiPicker({
  onSelect,
  onDelete,
  onSend,
  canSend,
  fill = false,
  backgroundColor,
  borderColor,
  primaryColor = '#0F766E',
  iconColor = '#6B7280',
  disabledColor = '#D1D5DB',
}: Props) {
  const entries = useMemo(
    () =>
      Object.keys(WECHAT_EMOJI_SOURCES)
        .map((name) => ({ name, uri: getWechatEmojiUri(name) }))
        .filter((e): e is { name: string; uri: string } => !!e.uri),
    [],
  );

  return (
    <View
      style={[
        fill ? styles.containerFill : styles.container,
        { backgroundColor, borderTopColor: borderColor },
        fill && { borderTopWidth: 0 },
      ]}
    >
      <ScrollView
        contentContainerStyle={styles.grid}
        keyboardShouldPersistTaps="always"
        showsVerticalScrollIndicator={false}
      >
        {entries.map(({ name, uri }) => (
          <Pressable
            key={name}
            onPress={() => onSelect(name)}
            style={({ pressed }) => [styles.item, pressed && styles.itemPressed]}
            accessibilityLabel={`表情 ${name}`}
          >
            <Image source={{ uri }} style={styles.emoji} resizeMode="contain" />
          </Pressable>
        ))}
      </ScrollView>

      <View
        style={[styles.actionPad, { backgroundColor: backgroundColor ?? '#FFF' }]}
        pointerEvents="box-none"
      >
        <View style={styles.actionBar} pointerEvents="box-none">
          <Pressable
            onPress={onDelete}
            hitSlop={6}
            style={({ pressed }) => [
              styles.deleteBtn,
              {
                backgroundColor: backgroundColor ?? '#FFF',
                borderColor: borderColor ?? '#E5E7EB',
              },
              pressed && styles.itemPressed,
            ]}
            accessibilityLabel="删除"
          >
            <RollbackOutlined size={22} color={iconColor} />
          </Pressable>
          <Pressable
            onPress={onSend}
            disabled={!canSend}
            style={({ pressed }) => [
              styles.sendBtn,
              { backgroundColor: canSend ? primaryColor : disabledColor },
              pressed && canSend && styles.itemPressed,
            ]}
            accessibilityLabel="发送"
          >
            <SendOutlined size={18} color="#FFF" />
          </Pressable>
        </View>
      </View>
    </View>
  );
});

export const EMOJI_PANEL_HEIGHT = PANEL_HEIGHT;

const styles = StyleSheet.create({
  container: {
    height: PANEL_HEIGHT,
    borderTopWidth: StyleSheet.hairlineWidth,
  },
  containerFill: {
    flex: 1,
    minHeight: 0,
  },
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    paddingHorizontal: 8,
    paddingTop: 10,
    paddingBottom: ACTION_RESERVED_SPACE,
  },
  item: {
    width: '12.5%',
    aspectRatio: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  itemPressed: {
    opacity: 0.5,
  },
  emoji: {
    width: 30,
    height: 30,
  },
  actionPad: {
    position: 'absolute',
    right: 0,
    bottom: -3,
    paddingLeft: 14,
    paddingRight: 10,
    paddingTop: 10,
    paddingBottom: 8,
    borderTopLeftRadius: 12,
    shadowColor: '#000',
    shadowOpacity: 0.12,
    shadowRadius: 8,
    shadowOffset: { width: -2, height: -2 },
    elevation: 6,
  },
  actionBar: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  deleteBtn: {
    width: 48,
    height: 36,
    borderRadius: 8,
    borderWidth: StyleSheet.hairlineWidth,
    alignItems: 'center',
    justifyContent: 'center',
  },
  sendBtn: {
    minWidth: 60,
    height: 36,
    borderRadius: 8,
    paddingHorizontal: 16,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
