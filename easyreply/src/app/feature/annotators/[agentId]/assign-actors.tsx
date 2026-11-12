// ============================================================
// 主管为下属客服指派独占客户（Actor）
// - 全部客户：POST /api/app/actors/list（每页 20 条）
// - 已指派：POST /api/app/supervisor/agents/exclusive_actors/list
// - 指派/撤销：exclusive_actors/grant|revoke
// ============================================================
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { router, useLocalSearchParams } from 'expo-router';

import { CustomNavBar } from '@/components/UI/CustomNavBar';
import { ScreenCanvas } from '@/components/UI/ScreenCanvas';
import { useTheme } from '@/design/theme-context';
import { Tokens } from '@/design/tokens';
import { CheckCircleFilled, SearchOutlined, ShopOutlined } from '@/ui/antd-icons';
import { fetchActorsList, type ActorItem } from '@/api/actors';
import {
  formatExclusiveActorError,
  grantExclusiveActor,
  listExclusiveActors,
  revokeExclusiveActor,
} from '@/api/supervisor';
import { appAlert } from '@/lib/app-alert';

const PAGE_SIZE = 20;

type AssignedRow = {
  actorID: string;
  shopName: string;
  skillGroup?: string;
};

export default function AssignActorsScreen() {
  const theme = useTheme();
  const { agentId, name } = useLocalSearchParams<{ agentId: string; name?: string }>();
  const targetAgentId = (agentId ?? '').trim();
  const agentName = name?.trim() || '客服';

  const [actors, setActors] = useState<ActorItem[]>([]);
  const [total, setTotal] = useState(0);
  const [exclusiveIds, setExclusiveIds] = useState<Set<string>>(() => new Set());
  const [keyword, setKeyword] = useState('');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const togglingRef = useRef<Set<string>>(new Set());
  const loadingMoreRef = useRef(false);

  const hasMore = actors.length < total;

  const loadExclusiveIds = useCallback(async () => {
    if (!targetAgentId) return new Set<string>();
    const res = await listExclusiveActors(targetAgentId);
    const ids = Array.isArray(res.exclusive_actor_ids) ? res.exclusive_actor_ids : [];
    return new Set(ids.map((id) => id.trim()).filter(Boolean));
  }, [targetAgentId]);

  const loadPage = useCallback(async (offset: number) => {
    const res = await fetchActorsList({ limit: PAGE_SIZE, offset });
    return {
      list: Array.isArray(res?.actors) ? res.actors : [],
      total: typeof res?.total === 'number' ? res.total : 0,
    };
  }, []);

  useEffect(() => {
    let alive = true;
    (async () => {
      setLoading(true);
      try {
        const [{ list, total: nextTotal }, exclusive] = await Promise.all([
          loadPage(0),
          loadExclusiveIds(),
        ]);
        if (!alive) return;
        setActors(list);
        setTotal(nextTotal);
        setExclusiveIds(exclusive);
      } catch (e) {
        if (!alive) return;
        setActors([]);
        setTotal(0);
        setExclusiveIds(new Set());
        appAlert('加载失败', formatExclusiveActorError(e));
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [loadPage, loadExclusiveIds]);

  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      const [{ list, total: nextTotal }, exclusive] = await Promise.all([
        loadPage(0),
        loadExclusiveIds(),
      ]);
      setActors(list);
      setTotal(nextTotal);
      setExclusiveIds(exclusive);
    } catch (e) {
      setActors([]);
      setTotal(0);
      appAlert('刷新失败', formatExclusiveActorError(e));
    } finally {
      setRefreshing(false);
    }
  }, [loadPage, loadExclusiveIds]);

  const handleLoadMore = useCallback(async () => {
    if (loading || refreshing || loadingMoreRef.current || !hasMore) return;
    loadingMoreRef.current = true;
    setLoadingMore(true);
    try {
      const { list, total: nextTotal } = await loadPage(actors.length);
      setActors((prev) => {
        const seen = new Set(prev.map((a) => a.actorID));
        const merged = [...prev];
        for (const item of list) {
          if (!seen.has(item.actorID)) merged.push(item);
        }
        return merged;
      });
      setTotal(nextTotal);
    } catch {
      // 保留已加载数据
    } finally {
      loadingMoreRef.current = false;
      setLoadingMore(false);
    }
  }, [actors.length, hasMore, loadPage, loading, refreshing]);

  const actorNameMap = useMemo(() => {
    const map = new Map<string, ActorItem>();
    for (const a of actors) {
      if (a.actorID) map.set(a.actorID, a);
    }
    return map;
  }, [actors]);

  const assignedRows = useMemo<AssignedRow[]>(() => {
    return Array.from(exclusiveIds).map((id) => {
      const hit = actorNameMap.get(id);
      return {
        actorID: id,
        shopName: hit?.shopName?.trim() || id,
        skillGroup: hit?.skillGroup,
      };
    });
  }, [exclusiveIds, actorNameMap]);

  const filtered = useMemo(() => {
    const q = keyword.trim().toLowerCase();
    if (!q) return actors;
    return actors.filter((a) => {
      const shop = (a.shopName ?? '').toLowerCase();
      const id = (a.actorID ?? '').toLowerCase();
      return shop.includes(q) || id.includes(q);
    });
  }, [actors, keyword]);

  const applyExclusiveIds = useCallback((ids: string[]) => {
    setExclusiveIds(new Set(ids.map((id) => id.trim()).filter(Boolean)));
  }, []);

  const handleToggle = useCallback(
    (actorIdRaw: string, preferRevoke?: boolean) => {
      const actorId = actorIdRaw.trim();
      if (!targetAgentId || !actorId) return;
      if (togglingRef.current.has(actorId)) return;

      const assigned = preferRevoke === true ? true : exclusiveIds.has(actorId);
      setExclusiveIds((prev) => {
        const next = new Set(prev);
        if (assigned) next.delete(actorId);
        else next.add(actorId);
        return next;
      });

      togglingRef.current.add(actorId);
      void (async () => {
        try {
          const res = assigned
            ? await revokeExclusiveActor({
                agent_id: targetAgentId,
                actor_platform_id: actorId,
              })
            : await grantExclusiveActor({
                agent_id: targetAgentId,
                actor_platform_id: actorId,
              });
          if (Array.isArray(res.exclusive_actor_ids)) {
            applyExclusiveIds(res.exclusive_actor_ids);
          } else {
            // 响应未带列表时，再拉一次事实源
            applyExclusiveIds(Array.from(await loadExclusiveIds()));
          }
        } catch (e) {
          setExclusiveIds((prev) => {
            const next = new Set(prev);
            if (assigned) next.add(actorId);
            else next.delete(actorId);
            return next;
          });
          appAlert(assigned ? '取消指派失败' : '指派失败', formatExclusiveActorError(e));
        } finally {
          togglingRef.current.delete(actorId);
        }
      })();
    },
    [applyExclusiveIds, exclusiveIds, loadExclusiveIds, targetAgentId],
  );

  return (
    <ScreenCanvas safeAreaTop={false}>
      <StatusBar style="dark" />
      <CustomNavBar title="指派客户" onBack={() => router.back()} rightMinWidth={64} />
      <View style={styles.page}>
        <Text style={[styles.hint, { color: theme.textSubtle }]}>
          为「{agentName}」指派独占客户，指派后该客户任务仅分配给此客服
        </Text>

        <View
          style={[
            styles.searchBox,
            { backgroundColor: theme.surface2, borderColor: theme.border },
          ]}
        >
          <SearchOutlined size={18} color={theme.placeholder} />
          <TextInput
            style={[styles.searchInput, { color: theme.text }]}
            placeholder="搜索店铺名称或 ID"
            placeholderTextColor={theme.placeholder}
            value={keyword}
            onChangeText={setKeyword}
            returnKeyType="search"
            clearButtonMode="while-editing"
          />
        </View>

        {loading ? (
          <View style={styles.loadingWrap}>
            <ActivityIndicator color={theme.primary} />
          </View>
        ) : (
          <FlatList
            data={filtered}
            keyExtractor={(item) => item.actorID}
            contentContainerStyle={[
              styles.listContent,
              filtered.length === 0 && styles.listContentEmpty,
            ]}
            ItemSeparatorComponent={() => <View style={{ height: 10 }} />}
            showsVerticalScrollIndicator={false}
            onEndReached={handleLoadMore}
            onEndReachedThreshold={0.3}
            refreshControl={
              <RefreshControl
                refreshing={refreshing}
                onRefresh={handleRefresh}
                tintColor={theme.primary}
                colors={[theme.primary]}
              />
            }
            ListHeaderComponent={
              assignedRows.length > 0 ? (
                <View style={styles.assignedSection}>
                  <Text style={[styles.sectionTitle, { color: theme.text }]}>
                    已指派（{assignedRows.length}）
                  </Text>
                  <View style={styles.assignedList}>
                    {assignedRows.map((item) => (
                      <View
                        key={item.actorID}
                        style={[
                          styles.row,
                          {
                            backgroundColor: theme.surface,
                            borderColor: theme.border,
                            marginBottom: 10,
                          },
                        ]}
                      >
                        <View style={[styles.iconWrap, { backgroundColor: theme.primarySoft }]}>
                          <CheckCircleFilled size={20} color={theme.primary} />
                        </View>
                        <View style={styles.rowBody}>
                          <Text style={[styles.shopName, { color: theme.text }]} numberOfLines={1}>
                            {item.shopName}
                          </Text>
                          <Text style={[styles.meta, { color: theme.textSubtle }]} numberOfLines={1}>
                            ID: {item.actorID}
                            {item.skillGroup ? ` · ${item.skillGroup}` : ''}
                          </Text>
                        </View>
                        <Pressable
                          onPress={() => handleToggle(item.actorID, true)}
                          style={({ pressed }) => [
                            styles.actionBtn,
                            {
                              backgroundColor: theme.surface2,
                              borderColor: theme.border,
                            },
                            pressed && { opacity: 0.75 },
                          ]}
                        >
                          <Text style={[styles.actionText, { color: theme.textMuted }]}>
                            取消指派
                          </Text>
                        </Pressable>
                      </View>
                    ))}
                  </View>
                  <Text style={[styles.sectionTitle, { color: theme.text, marginTop: 4 }]}>
                    全部客户
                  </Text>
                </View>
              ) : null
            }
            ListEmptyComponent={
              <View style={styles.empty}>
                <Text style={[styles.emptyText, { color: theme.textSubtle }]}>
                  {keyword.trim() ? '无匹配客户' : '暂无客户'}
                </Text>
              </View>
            }
            ListFooterComponent={
              loadingMore ? (
                <View style={styles.footerLoading}>
                  <ActivityIndicator color={theme.primary} />
                </View>
              ) : null
            }
            renderItem={({ item }) => {
              const assigned = exclusiveIds.has(item.actorID);
              return (
                <View
                  style={[
                    styles.row,
                    { backgroundColor: theme.surface, borderColor: theme.border },
                  ]}
                >
                  <View style={[styles.iconWrap, { backgroundColor: theme.primarySoft }]}>
                    <ShopOutlined size={20} color={theme.primary} />
                  </View>
                  <View style={styles.rowBody}>
                    <Text style={[styles.shopName, { color: theme.text }]} numberOfLines={1}>
                      {item.shopName?.trim() || '未命名店铺'}
                    </Text>
                    <Text style={[styles.meta, { color: theme.textSubtle }]} numberOfLines={1}>
                      ID: {item.actorID}
                      {item.skillGroup ? ` · ${item.skillGroup}` : ''}
                    </Text>
                  </View>
                  <Pressable
                    onPress={() => handleToggle(item.actorID)}
                    style={({ pressed }) => [
                      styles.actionBtn,
                      {
                        backgroundColor: assigned ? theme.surface2 : theme.primary,
                        borderColor: assigned ? theme.border : theme.primary,
                      },
                      pressed && { opacity: 0.75 },
                    ]}
                  >
                    <Text
                      style={[
                        styles.actionText,
                        { color: assigned ? theme.textMuted : '#FFF' },
                      ]}
                    >
                      {assigned ? '已指派' : '指派'}
                    </Text>
                  </Pressable>
                </View>
              );
            }}
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
  hint: {
    fontSize: 13,
    lineHeight: 18,
    marginBottom: Tokens.spacing[3],
  },
  searchBox: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    height: 40,
    paddingHorizontal: 12,
    borderRadius: 10,
    borderWidth: StyleSheet.hairlineWidth,
    marginBottom: Tokens.spacing[3],
  },
  searchInput: {
    flex: 1,
    fontSize: 15,
    paddingVertical: 0,
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
  assignedSection: {
    marginBottom: 10,
  },
  assignedList: {
    marginTop: 8,
  },
  sectionTitle: {
    fontSize: 14,
    fontWeight: '700',
    marginBottom: 4,
  },
  empty: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingTop: Tokens.spacing[8],
  },
  emptyText: {
    fontSize: 14,
  },
  footerLoading: {
    paddingVertical: 16,
    alignItems: 'center',
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
  iconWrap: {
    width: 40,
    height: 40,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
  rowBody: {
    flex: 1,
    minWidth: 0,
    gap: 2,
  },
  shopName: {
    fontSize: 15,
    fontWeight: '600',
  },
  meta: {
    fontSize: 12,
  },
  actionBtn: {
    minWidth: 68,
    height: 32,
    paddingHorizontal: 12,
    borderRadius: 8,
    borderWidth: StyleSheet.hairlineWidth,
    alignItems: 'center',
    justifyContent: 'center',
  },
  actionText: {
    fontSize: 13,
    fontWeight: '600',
  },
});
