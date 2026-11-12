// ============================================================
// 后台表情库面板（与本地自定义表情分离）
// - 全部：list 分页
// - 标签 chip（全部右侧）：search（tag_codes）
// ============================================================
import { useCallback, useRef } from 'react';
import {
  ActivityIndicator,
  Animated,
  FlatList,
  Image,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import type { StickerItem } from '@/api/stickers';
import { centerChipScrollX } from '@/chatMessage/stickerPack/centerChipScroll';
import type { CustomSticker } from '@/chatMessage/stickerPack/custom-stickers-store';
import { useRemoteStickers } from '@/chatMessage/stickerPack/useRemoteStickers';
import { useTheme } from '@/design/theme-context';
import { Tokens } from '@/design/tokens';

type Props = {
  active: boolean;
  onSelectSticker: (sticker: CustomSticker) => void;
};

const ALL_CHIP_KEY = '__all';

export function RemoteStickerPanel({ active, onSelectSticker }: Props) {
  const theme = useTheme();
  const remote = useRemoteStickers(active);
  const scrollRef = useRef<ScrollView>(null);
  const viewportW = useRef(0);
  const contentW = useRef(0);
  const chipLayouts = useRef<Record<string, { x: number; width: number }>>({});

  const handleSelect = useCallback(
    (item: StickerItem) => {
      onSelectSticker(remote.toSendable(item));
    },
    [onSelectSticker, remote.toSendable],
  );

  const centerChip = useCallback((key: string) => {
    const layout = chipLayouts.current[key];
    if (!layout || !scrollRef.current) return;
    const x = centerChipScrollX({
      viewportWidth: viewportW.current,
      contentWidth: contentW.current,
      chipX: layout.x,
      chipWidth: layout.width,
    });
    scrollRef.current.scrollTo({ x, animated: true });
  }, []);

  if (!active) return <View style={styles.container} />;

  return (
    <View style={[styles.container, { backgroundColor: '#FFFFFF' }]}>
      <View style={styles.filterBlock}>
        <ScrollView
          ref={scrollRef}
          horizontal
          showsHorizontalScrollIndicator={false}
          keyboardShouldPersistTaps="always"
          style={styles.hScroll}
          contentContainerStyle={styles.chipRow}
          onLayout={(e) => {
            viewportW.current = e.nativeEvent.layout.width;
          }}
          onContentSizeChange={(w) => {
            contentW.current = w;
          }}
        >
          <Chip
            label="全部"
            selected={remote.tagCodes.length === 0}
            onPress={() => {
              remote.onPressAll();
              centerChip(ALL_CHIP_KEY);
            }}
            onLayout={(x, width) => {
              chipLayouts.current[ALL_CHIP_KEY] = { x, width };
            }}
            activeColor={theme.primary}
            activeBg={theme.primarySoft}
            mutedColor={theme.textSubtle}
          />
          {remote.tags.map((t) => (
            <Chip
              key={t.code}
              label={t.name}
              selected={remote.tagCodes.includes(t.code)}
              onPress={() => {
                remote.onPressTag(t.code);
                centerChip(t.code);
              }}
              onLayout={(x, width) => {
                chipLayouts.current[t.code] = { x, width };
              }}
              activeColor={theme.primary}
              activeBg={theme.primarySoft}
              mutedColor={theme.textSubtle}
            />
          ))}
          {remote.optionsError ? (
            <Text style={[styles.hintInline, { color: theme.textSubtle }]}>标签暂不可用</Text>
          ) : null}
        </ScrollView>
      </View>

      {remote.loading && remote.items.length === 0 ? (
        <View style={styles.center}>
          <ActivityIndicator color={theme.primary} />
        </View>
      ) : remote.error && remote.items.length === 0 ? (
        <View style={styles.center}>
          <Text style={{ color: theme.textSubtle, marginBottom: 8 }}>{remote.error}</Text>
          <Pressable
            onPress={remote.reload}
            style={({ pressed }) => [
              styles.retryBtn,
              { borderColor: theme.divider, opacity: pressed ? 0.7 : 1 },
            ]}
          >
            <Text style={{ color: theme.primary, fontSize: 13, fontWeight: '600' }}>重试</Text>
          </Pressable>
        </View>
      ) : remote.items.length === 0 ? (
        <View style={styles.center}>
          <Text style={{ color: theme.textSubtle }}>暂无表情</Text>
        </View>
      ) : (
        <FlatList
          style={styles.list}
          data={remote.items}
          keyExtractor={(item) => item.uuid}
          numColumns={4}
          keyboardShouldPersistTaps="always"
          onEndReached={remote.onLoadMore}
          onEndReachedThreshold={0.35}
          contentContainerStyle={styles.grid}
          columnWrapperStyle={styles.gridRow}
          ListFooterComponent={
            remote.loadingMore ? (
              <View style={styles.footer}>
                <ActivityIndicator color={theme.primary} />
              </View>
            ) : null
          }
          renderItem={({ item }) => (
            <Pressable
              onPress={() => handleSelect(item)}
              style={({ pressed }) => [styles.cell, pressed && { opacity: 0.65 }]}
              accessibilityRole="button"
              accessibilityLabel={item.name || '发送表情'}
            >
              <Image source={{ uri: item.file_url }} style={styles.image} resizeMode="contain" />
            </Pressable>
          )}
        />
      )}
    </View>
  );
}

function Chip({
  label,
  selected,
  onPress,
  onLayout,
  activeColor,
  activeBg,
  mutedColor,
}: {
  label: string;
  selected: boolean;
  onPress: () => void;
  onLayout: (x: number, width: number) => void;
  activeColor: string;
  activeBg: string;
  mutedColor: string;
}) {
  const scale = useRef(new Animated.Value(1)).current;
  return (
    <Animated.View
      style={{ transform: [{ scale }] }}
      onLayout={(e) => {
        const { x, width } = e.nativeEvent.layout;
        onLayout(x, width);
      }}
    >
      <Pressable
        onPress={onPress}
        onPressIn={() => {
          Animated.timing(scale, { toValue: 0.94, duration: 90, useNativeDriver: true }).start();
        }}
        onPressOut={() => {
          Animated.timing(scale, { toValue: 1, duration: 160, useNativeDriver: true }).start();
        }}
        style={[
          styles.chip,
          { backgroundColor: selected ? activeBg : 'transparent' },
        ]}
      >
        <Text
          style={[styles.chipText, { color: selected ? activeColor : mutedColor }]}
          numberOfLines={1}
        >
          {label}
        </Text>
      </Pressable>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, minHeight: 0 },
  filterBlock: { flexGrow: 0, flexShrink: 0 },
  hScroll: { flexGrow: 0 },
  chipRow: {
    paddingHorizontal: Tokens.spacing[3],
    paddingTop: 6,
    paddingBottom: 4,
    gap: 6,
    alignItems: 'center',
  },
  chip: {
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  chipText: { fontSize: 12, fontWeight: '400' },
  hintInline: { fontSize: 12, paddingHorizontal: 4 },
  center: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 16,
  },
  list: { flex: 1 },
  retryBtn: {
    paddingHorizontal: 14,
    paddingVertical: 6,
    borderRadius: 14,
    borderWidth: StyleSheet.hairlineWidth * 2,
  },
  grid: {
    paddingHorizontal: Tokens.spacing[3],
    paddingTop: 4,
    paddingBottom: Tokens.spacing[3],
  },
  gridRow: {
    justifyContent: 'flex-start',
    gap: 10,
    marginBottom: 10,
  },
  cell: {
    width: 64,
    height: 64,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
  },
  image: { width: 56, height: 56 },
  footer: { paddingVertical: 10, alignItems: 'center' },
});
