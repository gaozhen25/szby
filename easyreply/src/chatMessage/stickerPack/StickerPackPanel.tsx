// ============================================================
// 表情包面板（心心 tab）：自定义表情网格 + 添加入口
// 仅在 active 时 hydrate / 加载图片资源
// ============================================================
import { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Image,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { PlusOutlined } from '@/ui/antd-icons';
import { router, type Href } from 'expo-router';

import { useTheme } from '@/design/theme-context';
import { Tokens } from '@/design/tokens';
import {
  ensureCustomStickersHydrated,
  getCustomStickersSnapshot,
  subscribeCustomStickers,
  type CustomSticker,
} from '@/chatMessage/stickerPack/custom-stickers-store';

type Props = {
  /** 面板可见且切到表情包 tab 时为 true */
  active: boolean;
  onSelectSticker: (sticker: CustomSticker) => void;
};

export function StickerPackPanel({ active, onSelectSticker }: Props) {
  const theme = useTheme();
  const [stickers, setStickers] = useState<CustomSticker[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!active) return;
    let alive = true;
    setLoading(true);
    void ensureCustomStickersHydrated()
      .then((list) => {
        if (!alive) return;
        setStickers(list);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });

    const off = subscribeCustomStickers((list) => {
      if (alive) setStickers(list);
    });
    // 订阅时若已 hydrate，用快照对齐一次
    setStickers(getCustomStickersSnapshot());

    return () => {
      alive = false;
      off();
    };
  }, [active]);

  const openManage = () => {
    router.push('/feature/chat/custom-stickers' as Href);
  };

  if (!active) {
    return <View style={styles.container} />;
  }

  return (
    <View style={[styles.container, { backgroundColor: '#FFFFFF' }]}>
      <Text style={[styles.sectionTitle, { color: theme.textSubtle }]}>添加的单个表情</Text>
      {loading && stickers.length === 0 ? (
        <View style={styles.loadingWrap}>
          <ActivityIndicator color={theme.primary} />
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={styles.grid}
          keyboardShouldPersistTaps="always"
          showsVerticalScrollIndicator={false}
        >
          <Pressable
            onPress={openManage}
            style={({ pressed }) => [
              styles.addCell,
              {
                borderColor: theme.text,
                backgroundColor: '#F3F4F6',
                opacity: pressed ? 0.7 : 1,
              },
            ]}
            accessibilityRole="button"
            accessibilityLabel="添加自定义表情"
          >
            <PlusOutlined size={28} color={theme.text} />
          </Pressable>

          {stickers.map((item) => (
            <Pressable
              key={item.id}
              onPress={() => onSelectSticker(item)}
              style={({ pressed }) => [styles.stickerCell, pressed && { opacity: 0.65 }]}
              accessibilityRole="button"
              accessibilityLabel="发送自定义表情"
            >
              <Image source={{ uri: item.url }} style={styles.stickerImage} resizeMode="contain" />
            </Pressable>
          ))}
        </ScrollView>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    minHeight: 0,
  },
  sectionTitle: {
    fontSize: 13,
    fontWeight: '500',
    paddingHorizontal: Tokens.spacing[3],
    paddingTop: Tokens.spacing[2],
    paddingBottom: 6,
  },
  loadingWrap: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    paddingHorizontal: Tokens.spacing[3],
    paddingBottom: Tokens.spacing[3],
    gap: 10,
  },
  addCell: {
    width: 64,
    height: 64,
    borderRadius: 10,
    borderWidth: 1.5,
    borderStyle: 'dashed',
    alignItems: 'center',
    justifyContent: 'center',
  },
  stickerCell: {
    width: 64,
    height: 64,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
  },
  stickerImage: {
    width: 56,
    height: 56,
  },
});
