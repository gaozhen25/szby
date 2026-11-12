// ============================================================
// 客服「我的收藏」— 已收藏 Audience 列表
// ============================================================
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { router } from 'expo-router';

import { CustomNavBar } from '@/components/UI/CustomNavBar';
import { ScreenCanvas } from '@/components/UI/ScreenCanvas';
import { useTheme } from '@/design/theme-context';
import { StarFilled, StarOutlined } from '@/ui/antd-icons';
import { Tokens } from '@/design/tokens';
import {
  formatCollectedAudienceError,
  listCollectedAudiences,
  removeCollectedAudience,
} from '@/api/agents';
import { appAlert } from '@/lib/app-alert';
import { getClaimedConversationsSnapshot } from '@/lib/claimed-conversations-store';

type FavoriteRow = {
  audiencePlatformID: string;
  nickname: string;
  avatarUrl?: string;
  avatarColor: string;
};

const AVATAR_PALETTE = ['#7FB0D8', '#E8A598', '#B8A8E8', '#E8A0B0', '#E8D4A0'];

function resolveFavoriteRows(ids: string[]): FavoriteRow[] {
  const convs = getClaimedConversationsSnapshot();
  const byAudience = new Map<string, { nickname: string; avatarUrl?: string }>();
  for (const c of convs) {
    const id = (c.audiencePlatformID ?? '').trim();
    if (!id || byAudience.has(id)) continue;
    byAudience.set(id, {
      nickname: c.audiencePlatformNickname?.trim() || c.to?.trim() || id,
      avatarUrl: c.audiencePlatformFaceURL,
    });
  }

  return ids.map((id, index) => {
    const hit = byAudience.get(id);
    return {
      audiencePlatformID: id,
      nickname: hit?.nickname || id,
      avatarUrl: hit?.avatarUrl,
      avatarColor: AVATAR_PALETTE[index % AVATAR_PALETTE.length],
    };
  });
}

export default function MyFavoritesScreen() {
  const theme = useTheme();
  const [rows, setRows] = useState<FavoriteRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const removingRef = useRef<Set<string>>(new Set());

  const loadList = useCallback(async () => {
    const res = await listCollectedAudiences();
    const ids = Array.isArray(res.collected_audience_ids)
      ? res.collected_audience_ids.map((id) => id.trim()).filter(Boolean)
      : [];
    return resolveFavoriteRows(ids);
  }, []);

  useEffect(() => {
    let alive = true;
    (async () => {
      setLoading(true);
      try {
        const next = await loadList();
        if (alive) setRows(next);
      } catch (e) {
        if (alive) {
          setRows([]);
          appAlert('加载失败', formatCollectedAudienceError(e));
        }
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [loadList]);

  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      setRows(await loadList());
    } catch (e) {
      appAlert('刷新失败', formatCollectedAudienceError(e));
    } finally {
      setRefreshing(false);
    }
  }, [loadList]);

  const handleRemove = useCallback((item: FavoriteRow) => {
    const id = item.audiencePlatformID;
    if (!id || removingRef.current.has(id)) return;

    appAlert('取消收藏', `确定取消收藏「${item.nickname}」？`, [
      { text: '取消', style: 'cancel' },
      {
        text: '取消收藏',
        style: 'destructive',
        onPress: () => {
          removingRef.current.add(id);
          const prev = rows;
          setRows((cur) => cur.filter((r) => r.audiencePlatformID !== id));
          void (async () => {
            try {
              const res = await removeCollectedAudience({ audience_platform_id: id });
              const ids = Array.isArray(res.collected_audience_ids)
                ? res.collected_audience_ids.map((x) => x.trim()).filter(Boolean)
                : [];
              setRows(resolveFavoriteRows(ids));
            } catch (e) {
              setRows(prev);
              appAlert('取消收藏失败', formatCollectedAudienceError(e));
            } finally {
              removingRef.current.delete(id);
            }
          })();
        },
      },
    ]);
  }, [rows]);

  const countLabel = useMemo(() => `共 ${rows.length} 人`, [rows.length]);

  return (
    <ScreenCanvas safeAreaTop={false}>
      <StatusBar style="dark" />
      <CustomNavBar title="我的收藏" onBack={() => router.back()} />
      <View style={styles.page}>
        {!loading ? (
          <View style={styles.topMeta}>
            <Text style={[styles.count, { color: theme.textSubtle }]}>{countLabel}</Text>
            <Text style={[styles.hint, { color: theme.textSubtle }]}>
              聊天列表左滑活跃对话可快捷 添加/取消 收藏
            </Text>
          </View>
        ) : null}

        {loading ? (
          <View style={styles.loadingWrap}>
            <ActivityIndicator color={theme.primary} />
          </View>
        ) : (
          <FlatList
            data={rows}
            keyExtractor={(item) => item.audiencePlatformID}
            contentContainerStyle={[
              styles.listContent,
              rows.length === 0 && styles.listContentEmpty,
            ]}
            ItemSeparatorComponent={() => <View style={{ height: 10 }} />}
            showsVerticalScrollIndicator={false}
            refreshControl={
              <RefreshControl
                refreshing={refreshing}
                onRefresh={handleRefresh}
                tintColor={theme.primary}
                colors={[theme.primary]}
              />
            }
            ListEmptyComponent={
              <View style={styles.empty}>
                <View style={styles.emptyTopSpacer} />
                <View style={[styles.emptyIcon, { backgroundColor: theme.surface2 }]}>
                  <StarOutlined size={36} color={theme.placeholder} />
                </View>
                <Text style={[styles.emptyText, { color: theme.textSubtle }]}>暂无收藏</Text>
                <View style={styles.emptyBottomSpacer} />
              </View>
            }
            renderItem={({ item }) => (
              <View
                style={[
                  styles.row,
                  { backgroundColor: theme.surface, borderColor: theme.border },
                ]}
              >
                <View style={[styles.avatar, { backgroundColor: item.avatarColor }]}>
                  <Text style={styles.avatarText}>
                    {(item.nickname || item.audiencePlatformID).charAt(0)}
                  </Text>
                </View>
                <View style={styles.rowBody}>
                  <Text style={[styles.name, { color: theme.text }]} numberOfLines={1}>
                    {item.nickname}
                  </Text>
                  <Text style={[styles.meta, { color: theme.textSubtle }]} numberOfLines={1}>
                    ID: {item.audiencePlatformID}
                  </Text>
                </View>
                <Pressable
                  onPress={() => handleRemove(item)}
                  hitSlop={8}
                  style={({ pressed }) => [
                    styles.removeBtn,
                    { borderColor: theme.border, backgroundColor: theme.surface2 },
                    pressed && { opacity: 0.75 },
                  ]}
                >
                  <StarFilled size={16} color="#F5A623" />
                  <Text style={[styles.removeText, { color: theme.textMuted }]}>取消</Text>
                </Pressable>
              </View>
            )}
          />
        )}
      </View>
    </ScreenCanvas>
  );
}

const styles = StyleSheet.create({
  page: {
    flex: 1,
    paddingHorizontal: Tokens.spacing[4],
    paddingTop: Tokens.spacing[3],
  },
  count: {
    fontSize: 13,
  },
  topMeta: {
    gap: 6,
    marginBottom: Tokens.spacing[3],
  },
  hint: {
    fontSize: 12,
    lineHeight: 17,
  },
  loadingWrap: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  listContent: {
    paddingBottom: Tokens.spacing[6],
  },
  listContentEmpty: {
    flexGrow: 1,
  },
  empty: {
    flex: 1,
    alignItems: 'center',
    gap: Tokens.spacing[3],
  },
  emptyTopSpacer: {
    flex: 1,
  },
  emptyBottomSpacer: {
    flex: 2,
  },
  emptyIcon: {
    width: 72,
    height: 72,
    borderRadius: 36,
    alignItems: 'center',
    justifyContent: 'center',
  },
  emptyText: {
    fontSize: 14,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingVertical: 12,
    paddingHorizontal: 12,
    borderRadius: Tokens.radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
  },
  avatar: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarText: {
    color: '#FFF',
    fontSize: 16,
    fontWeight: '700',
  },
  rowBody: {
    flex: 1,
    minWidth: 0,
    gap: 2,
  },
  name: {
    fontSize: 15,
    fontWeight: '600',
  },
  meta: {
    fontSize: 12,
  },
  removeBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    height: 32,
    paddingHorizontal: 10,
    borderRadius: 8,
    borderWidth: StyleSheet.hairlineWidth,
  },
  removeText: {
    fontSize: 13,
    fontWeight: '500',
  },
});
