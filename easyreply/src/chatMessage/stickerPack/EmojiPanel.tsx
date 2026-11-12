// ============================================================
// 表情面板：搜索 / 表情 / 我的 / 表情库
// - 本地自定义表情见 StickerPackPanel（不改动其内部逻辑）
// - 后台表情库见 RemoteStickerPanel
// - 搜索见 StickerSearchPanel
// ============================================================
import { memo, useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import { HeartOutlined, SearchOutlined, SmileOutlined } from '@/ui/antd-icons';

import { EmojiPicker } from '@/chatMessage/components/EmojiPicker';
import { StickerPackPanel } from '@/chatMessage/stickerPack/StickerPackPanel';
import { RemoteStickerPanel } from '@/chatMessage/stickerPack/RemoteStickerPanel';
import type { CustomSticker } from '@/chatMessage/stickerPack/custom-stickers-store';
import { useTheme } from '@/design/theme-context';

const PANEL_HEIGHT = 300;
const TAB_BAR_HEIGHT = 44;

type TabId = 'search' | 'emoji' | 'sticker' | 'remote';

type Props = {
  onSelectEmoji: (name: string) => void;
  onDelete: () => void;
  onSend: () => void;
  canSend: boolean;
  onSelectSticker: (sticker: CustomSticker) => void;
  backgroundColor?: string;
  borderColor?: string;
  primaryColor?: string;
  iconColor?: string;
  disabledColor?: string;
};

export const EmojiPanel = memo(function EmojiPanel({
  onSelectEmoji,
  onDelete,
  onSend,
  canSend,
  onSelectSticker,
  backgroundColor,
  borderColor,
  primaryColor,
  iconColor,
  disabledColor,
}: Props) {
  const theme = useTheme();
  const [tab, setTab] = useState<TabId>('emoji');
  /** 内容区白底；Tab 与输入条同色（theme.surface） */
  const contentBg = backgroundColor ?? '#FFFFFF';
  const tabBarBg = theme.surface;
  const border = borderColor ?? theme.divider;
  const muted = iconColor ?? theme.textSubtle;
  const accent = primaryColor ?? theme.primary;
  const tabActiveBg = theme.primarySoft;
  /** 搜索 tab 选中底：偏图二圆形浅底 */
  const searchActiveBg = theme.surface2;

  return (
    <View style={[styles.panel, { height: PANEL_HEIGHT, backgroundColor: contentBg }]}>
      <View style={[styles.tabBar, { backgroundColor: tabBarBg }]}>
        <Pressable
          onPress={() => setTab('search')}
          style={({ pressed }) => [
            styles.tabBtnRound,
            tab === 'search' && { backgroundColor: searchActiveBg },
            pressed && { opacity: 0.75 },
          ]}
          accessibilityRole="button"
          accessibilityState={{ selected: tab === 'search' }}
          accessibilityLabel="表情库"
        >
          <SearchOutlined
            size={20}
            color={tab === 'search' ? accent : muted}
          />
        </Pressable>
        <Pressable
          onPress={() => setTab('emoji')}
          style={({ pressed }) => [
            styles.tabBtn,
            tab === 'emoji' && { backgroundColor: tabActiveBg },
            pressed && { opacity: 0.75 },
          ]}
          accessibilityRole="button"
          accessibilityState={{ selected: tab === 'emoji' }}
          accessibilityLabel="表情"
        >
          <SmileOutlined
            size={22}
            color={tab === 'emoji' ? accent : muted}
          />
        </Pressable>
        <Pressable
          onPress={() => setTab('sticker')}
          style={({ pressed }) => [
            styles.tabBtn,
            tab === 'sticker' && { backgroundColor: tabActiveBg },
            pressed && { opacity: 0.75 },
          ]}
          accessibilityRole="button"
          accessibilityState={{ selected: tab === 'sticker' }}
          accessibilityLabel="我的表情"
        >
          <HeartOutlined
            size={20}
            color={tab === 'sticker' ? accent : muted}
          />
        </Pressable>
        {/* 暂时隐藏：表情库 tab
        <Pressable
          onPress={() => setTab('remote')}
          style={({ pressed }) => [
            styles.tabBtn,
            tab === 'remote' && { backgroundColor: tabActiveBg },
            pressed && { opacity: 0.75 },
          ]}
          accessibilityRole="button"
          accessibilityState={{ selected: tab === 'remote' }}
          accessibilityLabel="表情库"
        >
          <AppstoreOutlined
            size={20}
            color={tab === 'remote' ? accent : muted}
          />
        </Pressable>
        */}
      </View>

      <View style={[styles.body, { backgroundColor: contentBg }]}>
        {tab === 'search' ? (
          <RemoteStickerPanel active onSelectSticker={onSelectSticker} />
        ) : tab === 'emoji' ? (
          <EmojiPicker
            fill
            onSelect={onSelectEmoji}
            onDelete={onDelete}
            onSend={onSend}
            canSend={canSend}
            backgroundColor={contentBg}
            borderColor={border}
            primaryColor={primaryColor}
            iconColor={iconColor}
            disabledColor={disabledColor}
          />
        ) : tab === 'sticker' ? (
          <StickerPackPanel active={tab === 'sticker'} onSelectSticker={onSelectSticker} />
        ) : (
          <RemoteStickerPanel active={tab === 'remote'} onSelectSticker={onSelectSticker} />
        )}
      </View>
    </View>
  );
});

export const EMOJI_PANEL_HEIGHT = PANEL_HEIGHT;
export const EMOJI_TAB_BAR_HEIGHT = TAB_BAR_HEIGHT;

const styles = StyleSheet.create({
  panel: {},
  body: {
    flex: 1,
    minHeight: 0,
  },
  tabBar: {
    height: TAB_BAR_HEIGHT,
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 10,
    gap: 8,
  },
  tabBtn: {
    width: 40,
    height: 32,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
  /** 图二：圆形浅底 + 放大镜 */
  tabBtnRound: {
    width: 34,
    height: 34,
    borderRadius: 17,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
