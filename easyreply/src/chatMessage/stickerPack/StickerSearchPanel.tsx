// ============================================================
// 表情搜索面板（独立 tab）
// - 仅关键词搜索后台表情包
// ============================================================
import { useCallback } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Image,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { CloseCircleFilled, SearchOutlined } from '@/ui/antd-icons';

import type { StickerItem } from '@/api/stickers';
import type { CustomSticker } from '@/chatMessage/stickerPack/custom-stickers-store';
import { useStickerSearch } from '@/chatMessage/stickerPack/useStickerSearch';
import { useTheme } from '@/design/theme-context';
import { Tokens } from '@/design/tokens';

type Props = {
  active: boolean;
  onSelectSticker: (sticker: CustomSticker) => void;
};

export function StickerSearchPanel({ active, onSelectSticker }: Props) {
  const theme = useTheme();
  const search = useStickerSearch(active);

  const { toSendable } = search;
  const handleSelect = useCallback(
    (item: StickerItem) => {
      onSelectSticker(toSendable(item));
    },
    [onSelectSticker, toSendable],
  );

  if (!active) return <View style={styles.container} />;

  return (
    <View style={[styles.container, { backgroundColor: '#FFFFFF' }]}>
      <View style={[styles.searchRow, { backgroundColor: theme.surface2 }]}>
        <SearchOutlined size={16} color={theme.textSubtle} />
        <TextInput
          value={search.draftKeyword}
          onChangeText={search.setDraftKeyword}
          placeholder="搜索表情"
          placeholderTextColor={theme.placeholder}
          style={[styles.searchInput, { color: theme.text }]}
          returnKeyType="search"
          onSubmitEditing={search.onSubmitSearch}
          autoFocus={false}
        />
        {search.draftKeyword || search.keyword ? (
          <Pressable onPress={search.onClearSearch} hitSlop={8} accessibilityLabel="清除搜索">
            <CloseCircleFilled size={16} color={theme.textSubtle} />
          </Pressable>
        ) : null}
        <Pressable
          onPress={search.onSubmitSearch}
          hitSlop={6}
          style={({ pressed }) => pressed && { opacity: 0.65 }}
        >
          <Text style={[styles.searchBtn, { color: theme.primary }]}>搜索</Text>
        </Pressable>
      </View>

      {search.loading && search.items.length === 0 ? (
        <View style={styles.center}>
          <ActivityIndicator color={theme.primary} />
        </View>
      ) : search.error && search.items.length === 0 ? (
        <View style={styles.hintBlock}>
          <Text style={{ color: theme.textSubtle, marginBottom: 8 }}>{search.error}</Text>
          <Pressable
            onPress={() => void search.runSearch(search.keyword)}
            style={({ pressed }) => [
              styles.retryBtn,
              { borderColor: theme.divider, opacity: pressed ? 0.7 : 1 },
            ]}
          >
            <Text style={{ color: theme.primary, fontSize: 13, fontWeight: '600' }}>重试</Text>
          </Pressable>
        </View>
      ) : !search.searched ? (
        <View style={styles.hintBlock}>
          <Text style={{ color: theme.textSubtle, fontSize: 13 }}>输入关键词搜索表情</Text>
        </View>
      ) : search.items.length === 0 ? (
        <View style={styles.hintBlock}>
          <Text style={{ color: theme.textSubtle, fontSize: 13 }}>未找到相关表情</Text>
        </View>
      ) : (
        <FlatList
          data={search.items}
          keyExtractor={(item) => item.uuid}
          numColumns={4}
          keyboardShouldPersistTaps="always"
          contentContainerStyle={styles.grid}
          columnWrapperStyle={styles.gridRow}
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

const styles = StyleSheet.create({
  container: { flex: 1, minHeight: 0 },
  searchRow: {
    marginHorizontal: Tokens.spacing[3],
    marginTop: 6,
    marginBottom: 4,
    height: 32,
    borderRadius: 16,
    paddingHorizontal: 10,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  searchInput: {
    flex: 1,
    fontSize: 14,
    paddingVertical: 0,
  },
  searchBtn: { fontSize: 12, fontWeight: '400' },
  center: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 16,
  },
  hintBlock: {
    flexGrow: 0,
    paddingTop: 16,
    paddingHorizontal: 16,
    alignItems: 'center',
  },
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
});
