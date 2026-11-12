// ============================================================
// 应用内相册选图（安卓规避系统文件管理器 / DocumentsUI）
// - 使用 expo-media-library 列相册图片
// - 导航取消返回，不离开当前 App 栈
// ============================================================
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Image,
  Modal,
  Pressable,
  StyleSheet,
  Text,
  View,
  useWindowDimensions,
} from 'react-native';
import * as MediaLibrary from 'expo-media-library';
import { StatusBar } from 'expo-status-bar';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useTheme } from '@/design/theme-context';
import { Tokens } from '@/design/tokens';
import { appAlert } from '@/lib/app-alert';

export type AlbumPickedImage = {
  uri: string;
  width: number;
  height: number;
  fileName?: string;
  mimeType?: string;
};

type Props = {
  visible: boolean;
  onClose: () => void;
  onPick: (asset: AlbumPickedImage) => void;
};

const GAP = 2;
const NUM_COLUMNS = 4;
const PAGE_SIZE = 80;

export function AlbumImagePicker({ visible, onClose, onPick }: Props) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const { width: screenWidth } = useWindowDimensions();
  const cellSize = Math.floor((screenWidth - GAP * (NUM_COLUMNS - 1)) / NUM_COLUMNS);

  const [assets, setAssets] = useState<MediaLibrary.Asset[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [endCursor, setEndCursor] = useState<string | undefined>();
  const [hasNext, setHasNext] = useState(false);
  const [picking, setPicking] = useState(false);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  const loadPage = useCallback(async (after?: string) => {
    const page = await MediaLibrary.getAssetsAsync({
      first: PAGE_SIZE,
      after,
      mediaType: MediaLibrary.MediaType.photo,
      sortBy: [[MediaLibrary.SortBy.creationTime, false]],
    });
    return page;
  }, []);

  useEffect(() => {
    if (!visible) return;
    let alive = true;
    setAssets([]);
    setEndCursor(undefined);
    setHasNext(false);
    setLoading(true);

    void (async () => {
      try {
        const perm = await MediaLibrary.requestPermissionsAsync();
        if (!alive) return;
        if (!perm.granted) {
          appAlert('需要相册权限', '请在系统设置中允许访问相册');
          onCloseRef.current();
          return;
        }
        const page = await loadPage();
        if (!alive) return;
        setAssets(page.assets);
        setEndCursor(page.endCursor);
        setHasNext(page.hasNextPage);
      } catch (e) {
        if (!alive) return;
        appAlert('打开相册失败', e instanceof Error ? e.message : '请稍后重试');
        onCloseRef.current();
      } finally {
        if (alive) setLoading(false);
      }
    })();

    return () => {
      alive = false;
    };
  }, [visible, loadPage]);

  const loadMore = useCallback(async () => {
    if (!hasNext || loadingMore || !endCursor) return;
    setLoadingMore(true);
    try {
      const page = await loadPage(endCursor);
      setAssets((prev) => [...prev, ...page.assets]);
      setEndCursor(page.endCursor);
      setHasNext(page.hasNextPage);
    } catch {
      // ignore
    } finally {
      setLoadingMore(false);
    }
  }, [hasNext, loadingMore, endCursor, loadPage]);

  const handleSelect = useCallback(
    async (asset: MediaLibrary.Asset) => {
      if (picking) return;
      setPicking(true);
      try {
        const info = await MediaLibrary.getAssetInfoAsync(asset, {
          shouldDownloadFromNetwork: true,
        });
        const uri = (info.localUri || info.uri || asset.uri).trim();
        if (!uri) {
          appAlert('选图失败', '无法读取该图片，请换一张重试');
          return;
        }
        const nameHint =
          (info.filename || asset.filename || '').trim() || undefined;
        const mime =
          nameHint?.toLowerCase().endsWith('.gif')
            ? 'image/gif'
            : nameHint?.toLowerCase().endsWith('.png')
              ? 'image/png'
              : nameHint?.toLowerCase().endsWith('.webp')
                ? 'image/webp'
                : 'image/jpeg';
        onPick({
          uri,
          width: info.width || asset.width || 0,
          height: info.height || asset.height || 0,
          fileName: nameHint,
          mimeType: mime,
        });
        onClose();
      } catch (e) {
        appAlert('选图失败', e instanceof Error ? e.message : '请稍后重试');
      } finally {
        setPicking(false);
      }
    },
    [picking, onPick, onClose],
  );

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose}>
      <StatusBar style="dark" />
      <View style={[styles.root, { backgroundColor: theme.bg, paddingBottom: insets.bottom }]}>
        <View
          style={[
            styles.nav,
            {
              borderBottomColor: theme.divider,
              backgroundColor: theme.surface,
              paddingTop: insets.top,
            },
          ]}
        >
          <Pressable onPress={onClose} hitSlop={12} style={styles.navSide}>
            <Text style={[styles.navAction, { color: theme.text }]}>取消</Text>
          </Pressable>
          <Text style={[styles.navTitle, { color: theme.text }]} numberOfLines={1}>
            选择图片
          </Text>
          <View style={styles.navSide} />
        </View>

        {loading ? (
          <View style={styles.center}>
            <ActivityIndicator color={theme.primary} />
          </View>
        ) : assets.length === 0 ? (
          <View style={styles.center}>
            <Text style={{ color: theme.textSubtle }}>相册暂无图片</Text>
          </View>
        ) : (
          <FlatList
            data={assets}
            keyExtractor={(item) => item.id}
            numColumns={NUM_COLUMNS}
            onEndReached={loadMore}
            onEndReachedThreshold={0.4}
            contentContainerStyle={styles.list}
            ListFooterComponent={
              loadingMore ? (
                <View style={styles.footer}>
                  <ActivityIndicator color={theme.primary} />
                </View>
              ) : null
            }
            renderItem={({ item, index }) => {
              const col = index % NUM_COLUMNS;
              return (
                <Pressable
                  onPress={() => {
                    void handleSelect(item);
                  }}
                  disabled={picking}
                  style={({ pressed }) => [
                    {
                      width: cellSize,
                      height: cellSize,
                      marginRight: col === NUM_COLUMNS - 1 ? 0 : GAP,
                      marginBottom: GAP,
                      opacity: pressed || picking ? 0.7 : 1,
                    },
                  ]}
                >
                  <Image source={{ uri: item.uri }} style={styles.thumb} />
                </Pressable>
              );
            }}
          />
        )}
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  nav: {
    minHeight: 48,
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: Tokens.spacing[2],
    paddingBottom: 0,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  navSide: {
    minWidth: 56,
    height: 48,
    justifyContent: 'center',
  },
  navAction: {
    fontSize: 16,
    fontWeight: '500',
  },
  navTitle: {
    flex: 1,
    height: 48,
    textAlign: 'center',
    textAlignVertical: 'center',
    ...Tokens.typography.navSecondary,
    lineHeight: 48,
  },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  list: { paddingTop: GAP },
  thumb: { width: '100%', height: '100%', backgroundColor: 'rgba(0,0,0,0.06)' },
  footer: { paddingVertical: 16, alignItems: 'center' },
});
