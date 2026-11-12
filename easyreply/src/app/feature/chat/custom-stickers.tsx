// ============================================================
// 自定义表情管理页
// - 进入即操作态：多选 + 全选 / 删除
// - 加号：相册选图 → 上传 → URL 写入本地缓存（按账号，上限 100）
// ============================================================
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Image,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { router } from 'expo-router';
import * as ImagePicker from 'expo-image-picker';

import { uploadImageAsset } from '@/api/assets';
import { CustomNavBar } from '@/components/UI/CustomNavBar';
import { ScreenCanvas } from '@/components/UI/ScreenCanvas';
import { useTheme } from '@/design/theme-context';
import { CheckOutlined, PlusOutlined } from '@/ui/antd-icons';
import { Tokens } from '@/design/tokens';
import { appAlert } from '@/lib/app-alert';
import { AlbumImagePicker, type AlbumPickedImage } from '@/chatMessage/stickerPack/AlbumImagePicker';
import {
  addCustomSticker,
  ensureCustomStickersHydrated,
  MAX_CUSTOM_STICKERS,
  removeCustomStickers,
  subscribeCustomStickers,
  type CustomSticker,
} from '@/chatMessage/stickerPack';

const CELL = 72;
const GAP = 12;
const NUM_COLUMNS = 4;

export default function CustomStickersScreen() {
  const theme = useTheme();
  const [stickers, setStickers] = useState<CustomSticker[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const [albumOpen, setAlbumOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    void ensureCustomStickersHydrated()
      .then((list) => {
        if (alive) setStickers(list);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    const off = subscribeCustomStickers((list) => {
      if (!alive) return;
      setStickers(list);
      setSelectedIds((prev) => {
        if (prev.size === 0) return prev;
        const valid = new Set(list.map((s) => s.id));
        const next = new Set([...prev].filter((id) => valid.has(id)));
        return next.size === prev.size ? prev : next;
      });
    });
    return () => {
      alive = false;
      off();
    };
  }, []);

  const allSelected =
    stickers.length > 0 && stickers.every((s) => selectedIds.has(s.id));

  const toggleSelect = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const handleSelectAll = useCallback(() => {
    if (stickers.length === 0) return;
    if (allSelected) {
      setSelectedIds(new Set());
      return;
    }
    setSelectedIds(new Set(stickers.map((s) => s.id)));
  }, [stickers, allSelected]);

  const uploadPickedImage = useCallback(
    async (asset: {
      uri: string;
      width?: number;
      height?: number;
      fileName?: string | null;
      mimeType?: string | null;
      file?: unknown;
    }) => {
      setUploading(true);
      try {
        const pickerFile =
          asset.file && typeof Blob !== 'undefined' && asset.file instanceof Blob
            ? asset.file
            : undefined;
        const uploaded = await uploadImageAsset({
          uri: asset.uri,
          fileName:
            asset.fileName ||
            (pickerFile && 'name' in pickerFile
              ? String((pickerFile as File).name || '')
              : undefined),
          mimeType: asset.mimeType || pickerFile?.type,
          blob: pickerFile,
          width: asset.width,
          height: asset.height,
        });
        await addCustomSticker({
          url: uploaded.url,
          objectKey: uploaded.objectKey,
          width: asset.width,
          height: asset.height,
        });
      } catch (e) {
        appAlert('上传失败', e instanceof Error ? e.message : '请稍后重试');
      } finally {
        setUploading(false);
      }
    },
    [],
  );

  const handleAdd = useCallback(async () => {
    if (uploading) return;
    if (stickers.length >= MAX_CUSTOM_STICKERS) {
      appAlert('已达上限', `最多添加 ${MAX_CUSTOM_STICKERS} 个自定义表情`);
      return;
    }

    // 安卓：系统选图常落到「文件」且难返回；改用应用内相册
    if (Platform.OS === 'android') {
      setAlbumOpen(true);
      return;
    }

    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) {
      appAlert('需要相册权限', '请在系统设置中允许访问相册');
      return;
    }

    const picked = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      quality: 1,
      allowsEditing: false,
      preferredAssetRepresentationMode:
        ImagePicker.UIImagePickerPreferredAssetRepresentationMode.Current,
    });
    if (picked.canceled || !picked.assets?.[0]) return;
    await uploadPickedImage(picked.assets[0]);
  }, [uploading, stickers.length, uploadPickedImage]);

  const handleAlbumPick = useCallback(
    (asset: AlbumPickedImage) => {
      void uploadPickedImage(asset);
    },
    [uploadPickedImage],
  );

  const handleDelete = useCallback(() => {
    if (selectedIds.size === 0) return;
    appAlert('删除表情', `确认删除选中的 ${selectedIds.size} 个表情？`, [
      { text: '取消', style: 'cancel' },
      {
        text: '删除',
        style: 'destructive',
        onPress: () => {
          void (async () => {
            try {
              await removeCustomStickers([...selectedIds]);
              setSelectedIds(new Set());
            } catch (e) {
              appAlert('删除失败', e instanceof Error ? e.message : '请稍后重试');
            }
          })();
        },
      },
    ]);
  }, [selectedIds]);

  const data = useMemo(
    () =>
      [
        { type: 'add' as const },
        ...stickers.map((sticker) => ({ type: 'sticker' as const, sticker })),
      ],
    [stickers],
  );

  return (
    <ScreenCanvas safeAreaTop={false}>
      <StatusBar style="dark" />
      <CustomNavBar
        title={`添加的单个表情 (${stickers.length})`}
        onBack={() => router.back()}
      />

      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator color={theme.primary} />
        </View>
      ) : (
        <FlatList
          data={data}
          keyExtractor={(item, index) =>
            item.type === 'add' ? 'add' : item.sticker.id || `s-${index}`
          }
          numColumns={NUM_COLUMNS}
          contentContainerStyle={styles.listContent}
          columnWrapperStyle={styles.row}
          renderItem={({ item }) => {
            if (item.type === 'add') {
              const atLimit = stickers.length >= MAX_CUSTOM_STICKERS;
              return (
                <Pressable
                  onPress={() => void handleAdd()}
                  disabled={uploading || atLimit}
                  style={({ pressed }) => [
                    styles.addCell,
                    {
                      borderColor: atLimit ? theme.placeholder : theme.text,
                      backgroundColor: theme.surface,
                      opacity: pressed || uploading || atLimit ? 0.55 : 1,
                    },
                  ]}
                  accessibilityRole="button"
                  accessibilityLabel="从相册添加表情"
                >
                  {uploading ? (
                    <ActivityIndicator color={theme.textSubtle} />
                  ) : (
                    <PlusOutlined
                      size={32}
                      color={atLimit ? theme.placeholder : theme.text}
                    />
                  )}
                </Pressable>
              );
            }

            const selected = selectedIds.has(item.sticker.id);
            return (
              <Pressable
                onPress={() => toggleSelect(item.sticker.id)}
                style={({ pressed }) => [
                  styles.stickerCell,
                  { backgroundColor: theme.surface },
                  pressed && { opacity: 0.75 },
                ]}
              >
                <Image
                  source={{ uri: item.sticker.url }}
                  style={styles.stickerImage}
                  resizeMode="contain"
                />
                <View
                  style={[
                    styles.check,
                    {
                      backgroundColor: selected ? theme.primary : 'rgba(0,0,0,0.15)',
                      borderColor: '#FFF',
                    },
                  ]}
                >
                  {selected ? <CheckOutlined size={12} color="#FFF" /> : null}
                </View>
              </Pressable>
            );
          }}
        />
      )}

      <View
        style={[
          styles.editBar,
          {
            backgroundColor: theme.surface,
            borderTopColor: theme.divider,
          },
        ]}
      >
        <Pressable
          onPress={handleSelectAll}
          disabled={stickers.length === 0}
          style={({ pressed }) => pressed && stickers.length > 0 && { opacity: 0.6 }}
        >
          <Text
            style={[
              styles.editAction,
              { color: stickers.length > 0 ? theme.text : theme.placeholder },
            ]}
          >
            {allSelected ? '取消全选' : '全选'}
          </Text>
        </Pressable>
        <Pressable
          onPress={handleDelete}
          disabled={selectedIds.size === 0}
          style={({ pressed }) => pressed && selectedIds.size > 0 && { opacity: 0.6 }}
        >
          <Text
            style={[
              styles.editAction,
              {
                color: selectedIds.size > 0 ? theme.danger : theme.placeholder,
              },
            ]}
          >
            {selectedIds.size > 0 ? `删除(${selectedIds.size})` : '删除'}
          </Text>
        </Pressable>
      </View>

      {Platform.OS === 'android' ? (
        <AlbumImagePicker
          visible={albumOpen}
          onClose={() => setAlbumOpen(false)}
          onPick={handleAlbumPick}
        />
      ) : null}
    </ScreenCanvas>
  );
}

const styles = StyleSheet.create({
  center: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  listContent: {
    paddingHorizontal: Tokens.spacing[4],
    paddingTop: Tokens.spacing[4],
    paddingBottom: Tokens.spacing[8],
  },
  row: {
    gap: GAP,
    marginBottom: GAP,
  },
  addCell: {
    width: CELL,
    height: CELL,
    borderRadius: 12,
    borderWidth: 1.5,
    borderStyle: 'dashed',
    alignItems: 'center',
    justifyContent: 'center',
  },
  stickerCell: {
    width: CELL,
    height: CELL,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
  },
  stickerImage: {
    width: CELL - 12,
    height: CELL - 12,
  },
  check: {
    position: 'absolute',
    top: 4,
    right: 4,
    width: 18,
    height: 18,
    borderRadius: 9,
    borderWidth: 1.5,
    alignItems: 'center',
    justifyContent: 'center',
  },
  editBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'flex-end',
    gap: 30,
    paddingHorizontal: Tokens.spacing[5],
    paddingVertical: Tokens.spacing[4],
    borderTopWidth: StyleSheet.hairlineWidth,
  },
  editAction: {
    fontSize: 16,
    fontWeight: '500',
  },
});
