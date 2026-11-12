import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { router, useFocusEffect, type Href } from 'expo-router';
import { appAlert } from '@/lib/app-alert';
import {
  CHAT_CATEGORY_MAJOR_MAP,
  MOCK_CHAT_MAJOR_FILTERS,
  MOCK_CHAT_SUB_FILTERS,
  type ChatSubCategory,
  type MockConversation,
} from '@/mock/data';
import { useIMConnection } from '@/hooks/useChat';
import { dutyStatus } from '@/api/tasks';
import {
  addCollectedAudience,
  formatCollectedAudienceError,
  listCollectedAudiences,
  removeCollectedAudience,
} from '@/api/agents';
import { getAgentId } from '@/core/im';
import { waitForAuthBootstrap } from '@/core/auth-flow';
import { emitDutyState, saveDutyState } from '@/core/duty';
import { emitConversationListManualRefreshed } from '@/lib/conversation-list-refresh-bus';
import {
  getClaimedConversationsSnapshot,
  refreshClaimedConversations,
  removeInactiveClaimedConversation,
  removeInactiveClaimedConversationsMatching,
} from '@/lib/claimed-conversations-store';
import { clearChatMessagesCacheForConversations } from '@/chatMessage/message/chat-messages-cache';
import { conversationChatRouteParams, prefetchConversationChatCache } from '@/features/conversations/conversation-chat-params';
import {
  conversationActorId,
  extractConversationActors,
  matchesSelectedActor,
  canonicalActorPlatformId,
} from '@/features/conversations/conversation-actors';
import {
  formatConversationCountLabel,
  useMaxActiveCap,
} from '@/features/conversations/conversation-count-label';
import { useConversationListBatchActions } from '@/features/conversations/useConversationListBatchActions';
import { useConversationListBootstrap } from '@/features/conversations/useConversationListBootstrap';
import { useAckConversationPending } from '@/features/conversations/useAckConversationPending';
import { canAckConversationPending } from '@/features/conversations/ack-conversation-pending';
import { useClaimedConversationsSubscription } from '@/features/conversations/useClaimedConversationsSubscription';
import { useDutyControls } from '@/features/conversations/useDutyControls';
import { useIntakeControls } from '@/features/conversations/useIntakeControls';
import { getSiderActorBrand, hydrateSiderActorBrand } from '@/lib/sider-actor-brand-bus';

const REFRESH_BTN_COOLDOWN_MS = 5000;

export function conversationRowKey(conv: MockConversation): string {
  return (conv.imConversationID?.trim() || conv.id || '').trim();
}

export function conversationFavoriteKey(conv: MockConversation): string {
  return (conv.audiencePlatformID ?? '').trim();
}

function matchesConversationKeyword(conv: MockConversation, keyword: string): boolean {
  const q = keyword.trim().toLowerCase();
  if (!q) return true;
  return (
    (conv.actorPlatformNickname ?? '').toLowerCase().includes(q) ||
    (conv.audiencePlatformNickname ?? '').toLowerCase().includes(q) ||
    conv.from.toLowerCase().includes(q) ||
    conv.to.toLowerCase().includes(q)
  );
}

function getConversationMajor(categoryId: string): string {
  return CHAT_CATEGORY_MAJOR_MAP[categoryId] ?? categoryId;
}

function getSubFiltersForMajor(majorId: string): ChatSubCategory[] {
  if (majorId === 'all') return MOCK_CHAT_SUB_FILTERS;
  return MOCK_CHAT_SUB_FILTERS.filter((sub) => sub.id === 'all' || sub.majorId === majorId);
}

function matchesFilter(conv: MockConversation, majorId: string, subId: string): boolean {
  const convMajor = getConversationMajor(conv.categoryId);
  if (subId !== 'all') return conv.categoryId === subId;
  if (majorId !== 'all') return convMajor === majorId;
  return true;
}

function buildMajorUnreadMap(conversations: MockConversation[]): Record<string, number> {
  const map: Record<string, number> = { all: 0 };
  for (const major of MOCK_CHAT_MAJOR_FILTERS) {
    if (major.id !== 'all') map[major.id] = 0;
  }
  for (const conv of conversations) {
    map.all += conv.unread;
    const majorId = getConversationMajor(conv.categoryId);
    map[majorId] = (map[majorId] ?? 0) + conv.unread;
  }
  return map;
}

function buildSubUnreadMap(
  conversations: MockConversation[],
  majorId: string,
): Record<string, number> {
  const subs = getSubFiltersForMajor(majorId);
  const map: Record<string, number> = { all: 0 };
  for (const sub of subs) {
    if (sub.id !== 'all') map[sub.id] = 0;
  }
  for (const conv of conversations) {
    const convMajor = getConversationMajor(conv.categoryId);
    const inMajor = majorId === 'all' || convMajor === majorId;
    if (!inMajor) continue;
    map.all += conv.unread;
    map[conv.categoryId] = (map[conv.categoryId] ?? 0) + conv.unread;
  }
  return map;
}

export function useConversationList() {
  const { state: connectionState, isOnline, retry } = useIMConnection();
  const { isSupervisor, onDuty, setOnDuty, handleToggleDuty } = useDutyControls();
  const {
    isSupervisor: _intakeSupervisor,
    ...intakeControls
  } = useIntakeControls();
  const [keyword, setKeyword] = useState('');
  const [activeMajorId, setActiveMajorId] = useState('all');
  const [activeSubId, setActiveSubId] = useState('all');
  const { conversations, claimedCount } = useClaimedConversationsSubscription('mounted');
  const { blockingLoading, initialSyncing } = useConversationListBootstrap();
  const maxActiveCap = useMaxActiveCap();
  const [favoritedKeys, setFavoritedKeys] = useState<Set<string>>(() => new Set());
  const [refreshing, setRefreshing] = useState(false);
  const [refreshBtnCooldown, setRefreshBtnCooldown] = useState(false);
  const [favoritesModalVisible, setFavoritesModalVisible] = useState(false);
  const [selectedActorPlatformID, setSelectedActorPlatformID] = useState<string | null>(
    () => {
      const stored =
        hydrateSiderActorBrand()?.actorPlatformID ?? getSiderActorBrand()?.actorPlatformID ?? '';
      if (stored) return canonicalActorPlatformId(stored);
      return extractConversationActors(getClaimedConversationsSnapshot())[0]?.actorPlatformID ?? null;
    },
  );
  const favoritingRef = useRef<Set<string>>(new Set());
  const refreshBtnCooldownTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const headerSubtitle = formatConversationCountLabel(claimedCount, maxActiveCap);

  const openFavorites = useCallback(() => setFavoritesModalVisible(true), []);
  const closeFavorites = useCallback(() => setFavoritesModalVisible(false), []);
  const syncFavoritedKeys = useCallback((ids: string[]) => {
    setFavoritedKeys(new Set(ids.map((id) => id.trim()).filter(Boolean)));
  }, []);

  const openConversation = useCallback((item: MockConversation) => {
    prefetchConversationChatCache(item);
    router.push({
      pathname: '/chat/[id]',
      params: conversationChatRouteParams(item),
    } as unknown as Href);
  }, []);

  useFocusEffect(
    useCallback(() => {
      if (isSupervisor) return;
      let alive = true;
      void (async () => {
        if (!(await waitForAuthBootstrap())) return;
        const fav = await listCollectedAudiences().catch(() => null);
        if (!alive || !fav?.ok || !Array.isArray(fav.collected_audience_ids)) return;
        setFavoritedKeys(
          new Set(fav.collected_audience_ids.map((id) => id.trim()).filter(Boolean)),
        );
      })();
      return () => {
        alive = false;
      };
    }, [isSupervisor]),
  );

  useEffect(() => {
    let alive = true;
    void (async () => {
      if (!(await waitForAuthBootstrap())) return;
      const fav = await listCollectedAudiences().catch(() => null);
      if (!alive || !fav?.ok || !Array.isArray(fav.collected_audience_ids)) return;
      setFavoritedKeys(
        new Set(fav.collected_audience_ids.map((id) => id.trim()).filter(Boolean)),
      );
    })();
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    return () => {
      if (refreshBtnCooldownTimerRef.current) clearTimeout(refreshBtnCooldownTimerRef.current);
    };
  }, []);

  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      const [st] = await Promise.all([
        dutyStatus().catch(() => null),
        refreshClaimedConversations(),
      ]);
      if (st?.ok) {
        setOnDuty(st.on_duty);
        emitDutyState(st.on_duty);
        await saveDutyState(getAgentId(), st.on_duty).catch(() => {});
      }
      await intakeControls.refreshIntakeStatus();
      const fav = await listCollectedAudiences().catch(() => null);
      if (fav?.ok && Array.isArray(fav.collected_audience_ids)) {
        setFavoritedKeys(
          new Set(fav.collected_audience_ids.map((id) => id.trim()).filter(Boolean)),
        );
      }
    } catch {
      // ignore
    } finally {
      setRefreshing(false);
    }
  }, [setOnDuty, intakeControls.refreshIntakeStatus]);

  const startRefreshBtnCooldown = useCallback(() => {
    setRefreshBtnCooldown(true);
    if (refreshBtnCooldownTimerRef.current) clearTimeout(refreshBtnCooldownTimerRef.current);
    refreshBtnCooldownTimerRef.current = setTimeout(() => {
      setRefreshBtnCooldown(false);
      refreshBtnCooldownTimerRef.current = null;
    }, REFRESH_BTN_COOLDOWN_MS);
  }, []);

  const handleManualRefresh = useCallback(async () => {
    if (refreshing || refreshBtnCooldown) return;
    try {
      await handleRefresh();
      emitConversationListManualRefreshed();
    } finally {
      startRefreshBtnCooldown();
    }
  }, [handleRefresh, refreshing, refreshBtnCooldown, startRefreshBtnCooldown]);

  const majorUnreadMap = useMemo(() => buildMajorUnreadMap(conversations), [conversations]);
  const subFilters = useMemo(() => getSubFiltersForMajor(activeMajorId), [activeMajorId]);
  const subUnreadMap = useMemo(
    () => buildSubUnreadMap(conversations, activeMajorId),
    [activeMajorId, conversations],
  );

  const actors = useMemo(() => extractConversationActors(conversations), [conversations]);

  useEffect(() => {
    if (actors.length === 0) return;
    setSelectedActorPlatformID((prev) => {
      const stored = canonicalActorPlatformId(getSiderActorBrand()?.actorPlatformID ?? '');
      const canonicalPrev = prev ? canonicalActorPlatformId(prev) : '';
      if (stored && actors.some((a) => a.actorPlatformID === stored)) return stored;
      if (stored) return stored;
      if (canonicalPrev && actors.some((a) => a.actorPlatformID === canonicalPrev)) {
        return canonicalPrev;
      }
      return actors[0].actorPlatformID;
    });
  }, [actors]);

  const list = useMemo(() => {
    const seen = new Set<string>();
    return conversations
      .filter((c) => matchesFilter(c, activeMajorId, activeSubId))
      .filter((c) => matchesConversationKeyword(c, keyword))
      .filter((c) => matchesSelectedActor(c, selectedActorPlatformID))
      .filter((c) => {
        // 无主键的脏数据（如接管 upsert 缺 taskID）直接丢弃，避免 item.id.trim 崩溃
        const k = conversationRowKey(c);
        if (!k) return false;
        if (seen.has(k)) return false;
        seen.add(k);
        return true;
      });
  }, [keyword, activeMajorId, activeSubId, conversations, selectedActorPlatformID]);

  const activeList = useMemo(
    () => list.filter((c) => !c.inactive && !!c.id?.trim()),
    [list],
  );
  const batch = useConversationListBatchActions(activeList);
  const { ackProcessed, isAckSubmitting } = useAckConversationPending();

  const selectActor = useCallback((actorPlatformID: string) => {
    const id = canonicalActorPlatformId(actorPlatformID);
    if (!id) return;
    setSelectedActorPlatformID((prev) => (prev === id ? prev : id));
  }, []);

  const selectActorByConversation = useCallback(
    (conversationId: string) => {
      const id = conversationId.trim();
      if (!id) return;
      const conv = conversations.find((c) => c.id === id || c.imConversationID === id);
      const actorId = conversationActorId(conv);
      if (actorId) setSelectedActorPlatformID(actorId);
    },
    [conversations],
  );

  const actorFilterRef = useRef<string | null>(null);
  useEffect(() => {
    const prev = actorFilterRef.current;
    actorFilterRef.current = selectedActorPlatformID;
    if (prev == null || prev === selectedActorPlatformID) return;
    batch.cancelBatchSelect();
  }, [selectedActorPlatformID, batch.cancelBatchSelect]);

  const toggleFavorite = useCallback(
    (item: MockConversation) => {
      if (item.inactive) return;
      const audienceId = conversationFavoriteKey(item);
      if (!audienceId) {
        appAlert('收藏失败', '缺少用户标识，无法收藏');
        return;
      }
      if (favoritingRef.current.has(audienceId)) return;

      const wasFavorited = favoritedKeys.has(audienceId);
      setFavoritedKeys((prev) => {
        const next = new Set(prev);
        if (wasFavorited) next.delete(audienceId);
        else next.add(audienceId);
        return next;
      });

      favoritingRef.current.add(audienceId);
      void (async () => {
        try {
          const res = wasFavorited
            ? await removeCollectedAudience({ audience_platform_id: audienceId })
            : await addCollectedAudience({ audience_platform_id: audienceId });
          if (Array.isArray(res.collected_audience_ids)) {
            setFavoritedKeys(
              new Set(res.collected_audience_ids.map((id) => id.trim()).filter(Boolean)),
            );
          }
        } catch (e) {
          setFavoritedKeys((prev) => {
            const next = new Set(prev);
            if (wasFavorited) next.add(audienceId);
            else next.delete(audienceId);
            return next;
          });
          appAlert(
            wasFavorited ? '取消收藏失败' : '收藏失败',
            formatCollectedAudienceError(e),
          );
        } finally {
          favoritingRef.current.delete(audienceId);
        }
      })();
    },
    [favoritedKeys],
  );

  const deleteInactive = useCallback((item: MockConversation) => {
    if (!item.inactive) return;
    const title = (item.audiencePlatformNickname || item.to || '').trim() || '该会话';
    appAlert('删除会话', `将删除「${title}」及其本地聊天记录，确认继续？`, [
      { text: '取消', style: 'cancel' },
      {
        text: '删除',
        style: 'destructive',
        onPress: () => {
          void (async () => {
            try {
              const imId = await removeInactiveClaimedConversation(
                { imConversationID: item.imConversationID, id: item.id },
                'swipe_remove_inactive',
              );
              if (imId === null) {
                appAlert('删除失败', '仅可删除置灰会话，或会话已不存在');
                return;
              }
              if (imId) {
                await clearChatMessagesCacheForConversations([imId], 'swipe_remove_inactive');
              }
            } catch (e) {
              appAlert('删除失败', e instanceof Error ? e.message : '请稍后重试');
            }
          })();
        },
      },
    ]);
  }, []);

  const deleteInactiveForActor = useCallback(
    (actorPlatformID: string, openConversationId?: string) => {
      const actorId = canonicalActorPlatformId(actorPlatformID);
      if (!actorId) return;
      const targets = conversations.filter(
        (c) => c.inactive && conversationActorId(c) === actorId,
      );
      if (targets.length === 0) return;
      const actorName =
        actors.find((a) => a.actorPlatformID === actorId)?.nickname?.trim() || actorId;
      appAlert(
        '删除历史会话',
        `将删除「${actorName}」下 ${targets.length} 条历史会话及其本地聊天记录，确认继续？`,
        [
          { text: '取消', style: 'cancel' },
          {
            text: '删除',
            style: 'destructive',
            onPress: () => {
              void (async () => {
                try {
                  const removed = await removeInactiveClaimedConversationsMatching(
                    (c) => conversationActorId(c) === actorId,
                    'actor_clear_inactive',
                  );
                  if (
                    removed.imConversationIDs.length === 0 &&
                    removed.taskIDs.length === 0
                  ) {
                    appAlert('删除失败', '没有可删除的历史会话，或会话已不存在');
                    return;
                  }
                  if (removed.imConversationIDs.length > 0) {
                    await clearChatMessagesCacheForConversations(
                      removed.imConversationIDs,
                      'actor_clear_inactive',
                    );
                  }
                  const openId = openConversationId?.trim();
                  if (
                    openId &&
                    (removed.taskIDs.includes(openId) ||
                      removed.imConversationIDs.includes(openId))
                  ) {
                    router.setParams({ id: '', annotatorId: '', supervisor: '' });
                  }
                } catch (e) {
                  appAlert('删除失败', e instanceof Error ? e.message : '请稍后重试');
                }
              })();
            },
          },
        ],
      );
    },
    [actors, conversations],
  );

  const bannerMode = !isOnline
    ? 'offline'
    : connectionState === 'connection_timeout'
      ? 'timeout'
      : connectionState === 'reconnecting'
        ? 'reconnecting'
        : connectionState !== 'connected'
          ? 'connecting'
          : null;

  return {
    isSupervisor,
    headerSubtitle,
    onDuty,
    keyword,
    setKeyword,
    activeMajorId,
    activeSubId,
    majorFilters: MOCK_CHAT_MAJOR_FILTERS,
    subFilters,
    majorUnreadMap,
    subUnreadMap,
    list,
    actors,
    selectedActorPlatformID,
    selectActor,
    selectActorByConversation,
    loading: blockingLoading,
    refreshing: refreshing || initialSyncing,
    refreshBtnCooldown,
    favoritedKeys,
    bannerMode,
    retry,
    handleSelectMajor: (id: string) => {
      setActiveMajorId(id);
      setActiveSubId('all');
    },
    handleSelectSub: (id: string) => setActiveSubId(id),
    handleToggleDuty,
    handleManualRefresh,
    openConversation,
    toggleFavorite,
    ackProcessed,
    isAckSubmitting,
    canAckConversationPending,
    deleteInactive,
    deleteInactiveForActor,
    favoritesModalVisible,
    openFavorites,
    closeFavorites,
    syncFavoritedKeys,
    ...intakeControls,
    ...batch,
  };
}
