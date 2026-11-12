// ============================================================
// 聊天 - 会话列表
// ============================================================
import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { router, useFocusEffect, type Href } from 'expo-router';
import { SwipeListView } from 'react-native-swipe-list-view';

import {
  CachedImage,
  ChatFilterPanel,
  ConnectionBanner,
  EmojiText,
  type ConnectionBannerMode,
} from '@/chatMessage';
import { ScreenCanvas } from '@/components/UI/ScreenCanvas';
import { ScreenHeader } from '@/components/UI/ScreenHeader';
import { ChatType } from '@/design/chat-type';
import { useTheme } from '@/design/theme-context';
import { Tokens } from '@/design/tokens';
import { appAlert } from '@/lib/app-alert';
import {
  CHAT_CATEGORY_MAJOR_MAP,
  MOCK_CHAT_MAJOR_FILTERS,
  MOCK_CHAT_SUB_FILTERS,
  type ChatPlatform,
  type ChatSubCategory,
  type MockConversation,
  hasConversationProactiveHint,
  hasConversationAdoptionReview,
} from '@/mock/data';
import { useIMConnection } from '@/hooks/useChat';
import { dutyOff, dutyOn, dutyStatus } from '@/api/tasks';
import {
  addCollectedAudience,
  formatCollectedAudienceError,
  listCollectedAudiences,
  removeCollectedAudience,
} from '@/api/agents';
import { getRole } from '@/core/auth';
import { waitForAuthBootstrap } from '@/core/auth-flow';
import { getAgentId } from '@/core/im';
import { loadDutyState, saveDutyState, subscribeDutyState } from '@/core/duty';
import {
  ensureClaimedConversationsHydrated,
  getClaimedConversationsSnapshot,
  refreshClaimedConversations,
  removeInactiveClaimedConversation,
  syncClaimedListAfterDutyOff,
  cancelSyncClaimedListAfterDutyOff,
} from '@/lib/claimed-conversations-store';
import { clearChatMessagesCacheForConversations } from '@/chatMessage/message/chat-messages-cache';
import { conversationChatRouteParams, prefetchConversationChatCache } from '@/features/conversations/conversation-chat-params';
import {
  formatConversationCountLabel,
  useMaxActiveCap,
} from '@/features/conversations/conversation-count-label';
import { useConversationListBatchActions } from '@/features/conversations/useConversationListBatchActions';
import { useAckConversationPending } from '@/features/conversations/useAckConversationPending';
import { canAckConversationPending } from '@/features/conversations/ack-conversation-pending';
import { conversationPairLabel } from '@/features/conversations/conversation-actors';
import { BatchCompleteConfirmModal } from '@/features/conversations/BatchCompleteConfirmModal';
import { ConversationListMoreSheet } from '@/features/conversations/ConversationListMoreSheet';
import { TransferAgentPicker } from '@/features/conversations/TransferAgentPicker';
import { useClaimedConversationsSubscription } from '@/features/conversations/useClaimedConversationsSubscription';
import { IntakeStatusBar } from '@/features/conversations/IntakeStatusBar';
import { useIntakeControls } from '@/features/conversations/useIntakeControls';
import {
  CheckOutlined,
  CheckCircleOutlined,
  DeleteOutlined,
  MessageOutlined,
  MoonOutlined,
  MoreOutlined,
  ReloadOutlined,
  StarFilled,
  StarOutlined,
  WifiOutlined,
} from '@/ui/antd-icons';
import { SearchInputGlyph } from '@/ui/mobile-glyphs';

const PROACTIVE_HINT_DOT = '#FACC15';
const ADOPTION_REVIEW_COLOR = '#0B6E4F';
/** 左滑露出操作按钮宽度（活跃=已处理+收藏，置灰=删除） */
const SWIPE_ACTION_WIDTH = 88;
const SWIPE_ACTIVE_OPEN_WIDTH = SWIPE_ACTION_WIDTH * 2;
/**
 * 会话行固定高度 = 头像 44 + 上下 padding 12×2 + 分割线。
 * 行内元素（正文两行 38、右侧时间+徽标 36）都不超过 44，因此高度恒定，
 * 可以给 FlatList 提供 getItemLayout，省掉数百行的逐行测量。
 */
const CONVERSATION_ROW_HEIGHT = 68 + StyleSheet.hairlineWidth;

/** FlatList 唯一 key：优先 imConversationID，兜底 taskID */
function conversationRowKey(conv: MockConversation): string {
  return (conv.imConversationID?.trim() || conv.id || '').trim();
}

/** 收藏态 key：Audience platform id */
function conversationFavoriteKey(conv: MockConversation): string {
  return (conv.audiencePlatformID ?? '').trim();
}

function matchesConversationKeyword(conv: MockConversation, keyword: string): boolean {
  const q = keyword.trim().toLowerCase();
  if (!q) return true;
  return (
    (conv.actorPlatformNickname ?? '').toLowerCase().includes(q) ||
    (conv.audiencePlatformNickname ?? '').toLowerCase().includes(q) ||
    // 兼容展示名（昵称为空时 from/to 会回退到平台 id）
    conv.from.toLowerCase().includes(q) ||
    conv.to.toLowerCase().includes(q)
  );
}

function getConversationMajor(categoryId: string): string {
  return CHAT_CATEGORY_MAJOR_MAP[categoryId] ?? categoryId;
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

function getSubFiltersForMajor(majorId: string): ChatSubCategory[] {
  if (majorId === 'all') return MOCK_CHAT_SUB_FILTERS;
  return MOCK_CHAT_SUB_FILTERS.filter((sub) => sub.id === 'all' || sub.majorId === majorId);
}

function matchesFilter(
  conv: MockConversation,
  majorId: string,
  subId: string,
): boolean {
  const convMajor = getConversationMajor(conv.categoryId);
  if (subId !== 'all') return conv.categoryId === subId;
  if (majorId !== 'all') return convMajor === majorId;
  return true;
}

const PLATFORM_STYLE: Record<ChatPlatform, { bg: string; text: string }> = {
  微信: { bg: '#E6F6EC', text: '#15803D' },
  抖音: { bg: '#FFE8EC', text: '#C41E3A' },
};

function PlatformTag({ platform }: { platform: ChatPlatform }) {
  const style = PLATFORM_STYLE[platform];
  return (
    <View style={[styles.platformTag, { backgroundColor: style.bg }]}>
      <Text style={[styles.platformText, { color: style.text }]}>{platform}</Text>
    </View>
  );
}

function ConversationAvatar({
  url,
  color,
  muted,
  fallbackText,
}: {
  url?: string;
  color: string;
  muted?: boolean;
  /** 无头像图时展示的文字（取 audiencePlatformNickname 首字） */
  fallbackText?: string;
}) {
  const [failed, setFailed] = useState(false);
  const avatarUrl = url?.trim();
  const showImage = !!avatarUrl && !failed;
  const letter = (fallbackText ?? '').trim().charAt(0);

  return (
    <View
      style={[
        styles.avatar,
        { backgroundColor: color, overflow: 'hidden' },
        muted && { opacity: 0.45 },
      ]}
    >
      {showImage ? (
        <CachedImage
          source={{ uri: avatarUrl }}
          style={styles.avatarImage}
          contentFit="cover"
          onError={() => setFailed(true)}
        />
      ) : letter ? (
        <View style={styles.avatarFallback}>
          <Text style={styles.avatarFallbackText}>{letter}</Text>
        </View>
      ) : null}
    </View>
  );
}

function ConversationStatusDots({
  hasRedDot,
  hasProactiveHint,
  muted,
}: {
  hasRedDot: boolean;
  hasProactiveHint: boolean;
  muted: boolean;
}) {
  const theme = useTheme();
  if (muted) return null;

  const red = hasRedDot;
  const yellow = hasProactiveHint;
  if (!red && !yellow) return null;

  if (red && yellow) {
    return (
      <View style={styles.dotRow}>
        <View style={[styles.dotCircle, { backgroundColor: PROACTIVE_HINT_DOT }]} />
        <View
          style={[
            styles.dotCircle,
            styles.dotCircleOverlap,
            { backgroundColor: theme.danger },
          ]}
        />
      </View>
    );
  }

  return (
    <View
      style={[
        styles.dotCircle,
        { backgroundColor: red ? theme.danger : PROACTIVE_HINT_DOT },
      ]}
    />
  );
}

const ConversationItem = memo(function ConversationItem({
  item,
  favorited,
  batchSelectMode,
  batchChecked,
  onPress,
  onToggleBatch,
}: {
  item: MockConversation;
  favorited?: boolean;
  batchSelectMode?: boolean;
  batchChecked?: boolean;
  onPress: (item: MockConversation) => void;
  onToggleBatch?: (taskID: string) => void;
}) {
  const theme = useTheme();
  const muted = item.inactive;
  const avatarLetter =
    item.audiencePlatformNickname?.trim() || item.to?.trim() || '';
  const hasProactiveHint = hasConversationProactiveHint(item);
  const hasAdoptionReview = hasConversationAdoptionReview(item);

  return (
    <Pressable
      style={[
        styles.convItem,
        batchChecked ? styles.convItemBatchSelected : null,
        { borderBottomColor: theme.divider, backgroundColor: theme.bg },
      ]}
      onPress={() => {
        if (batchSelectMode && !muted) {
          const id = (item.id ?? '').trim();
          if (id) onToggleBatch?.(id);
        } else onPress(item);
      }}
      disabled={batchSelectMode && muted}
    >
      {/* 置灰只弱化内容，不降低整行透明度，避免 SwipeListView 透底 */}
      <View style={[styles.convItemInner, muted && styles.convItemInnerMuted]}>
        {batchSelectMode ? (
          <View
            style={[
              styles.batchCheck,
              {
                borderColor: batchChecked ? theme.primary : theme.border,
                backgroundColor: batchChecked ? theme.primary : theme.surface,
              },
            ]}
          >
            {batchChecked ? <CheckOutlined size={12} color="#FFFFFF" /> : null}
          </View>
        ) : null}
        <View style={styles.avatarWrap}>
          <ConversationAvatar
            url={item.audiencePlatformFaceURL}
            color={item.avatarColor}
            muted={muted}
            fallbackText={avatarLetter}
          />
          {item.unread > 0 ? (
            <View style={[styles.badge, { backgroundColor: theme.danger }]}>
              <Text style={styles.badgeText}>{item.unread}</Text>
            </View>
          ) : null}
        </View>

        <View style={styles.convBody}>
          <View style={styles.convTitleRow}>
            <Text
              style={[
                styles.convTitle,
                { color: muted ? ChatType.color.placeholder : ChatType.color.nameLabel },
              ]}
              numberOfLines={1}
              ellipsizeMode="middle"
            >
              {conversationPairLabel(item) || '会话'}
            </Text>
            {favorited && !muted ? (
              <View style={styles.favoriteStar}>
                <StarFilled size={14} color="#F5A623" style={{ color: '#F5A623', fontSize: 14 }} />
              </View>
            ) : null}
          </View>
          <EmojiText
            text={item.preview}
            color={muted ? ChatType.color.placeholder : ChatType.color.subLabel}
            textStyle={styles.convPreview}
            variant="preview"
          />
        </View>

        <View style={styles.convMeta}>
          <Text
            style={[
              styles.convTime,
              { color: muted ? ChatType.color.placeholder : ChatType.color.timestamp },
            ]}
          >
            {item.time}
          </Text>
          <View style={styles.convMetaBottom}>
            {!muted && hasAdoptionReview ? (
              <Text style={styles.adoptionReviewBadge}>AI复审</Text>
            ) : null}
            <ConversationStatusDots
              hasRedDot={!!item.hasRedDot}
              hasProactiveHint={hasProactiveHint}
              muted={!!muted}
            />
          </View>
        </View>
      </View>
    </Pressable>
  );
});

const OFF_DUTY_ICON = '#8B5E3C';

function DutyStatusButton({
  onDuty,
  onToggle,
}: {
  onDuty: boolean;
  onToggle: () => void;
}) {
  const theme = useTheme();

  return (
    <Pressable
      onPress={onToggle}
      style={({ pressed }) => [
        styles.statusBadge,
        onDuty
          ? {
              backgroundColor: theme.successSoft,
              borderColor: theme.success + '33',
              borderWidth: StyleSheet.hairlineWidth,
            }
          : {
              backgroundColor: theme.surface2,
              borderColor: theme.border,
              borderWidth: StyleSheet.hairlineWidth,
            },
        pressed && { opacity: 0.88, transform: [{ scale: 0.98 }] },
      ]}
      accessibilityRole="button"
      accessibilityLabel={onDuty ? '上班中，点击切换为已下班' : '已下班，点击切换为上班中'}
    >
      {onDuty ? (
        <WifiOutlined size={15} color={theme.success} />
      ) : (
        <MoonOutlined size={15} color={OFF_DUTY_ICON} />
      )}
      <Text style={[styles.statusText, { color: theme.text }]}>
        {onDuty ? '上班中' : '已下班'}
      </Text>
    </Pressable>
  );
}

export default function ChatScreen() {
  const theme = useTheme();
  const { state: connectionState, isOnline, retry } = useIMConnection();
  // 默认已下班；会从本地持久化恢复
  const [onDuty, setOnDuty] = useState(false);
  const isSupervisor = getRole() === 'supervisor';
  const intake = useIntakeControls();
  const [keyword, setKeyword] = useState('');
  const [filterOpen, setFilterOpen] = useState(false);
  const [activeMajorId, setActiveMajorId] = useState('all');
  const [activeSubId, setActiveSubId] = useState('all');
  const { conversations, claimedCount } = useClaimedConversationsSubscription('focused');
  const maxActiveCap = useMaxActiveCap();
  /** 收藏态（key = audiencePlatformID） */
  const [favoritedKeys, setFavoritedKeys] = useState<Set<string>>(() => new Set());
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const favoritingRef = useRef<Set<string>>(new Set());
  const refreshBtnCooldownTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  /** Web 左滑松手会合成 click：滑动期间/刚结束后吞掉进房，且不自动收起 */
  const swipeGuardUntilRef = useRef(0);
  const openRowKeyRef = useRef<string | null>(null);
  const rowMapRef = useRef<Record<string, { closeRow: () => void }>>({});
  /** 仅滑动/展开时挂载彩色操作层，避免 Web 亚像素缝透出红线 */
  const [swipeRevealKeys, setSwipeRevealKeys] = useState<Set<string>>(() => new Set());
  const [refreshBtnCooldown, setRefreshBtnCooldown] = useState(false);

  const REFRESH_BTN_COOLDOWN_MS = 5000;
  const SWIPE_PRESS_GUARD_MS = 450;

  const markSwipeGuard = useCallback(() => {
    swipeGuardUntilRef.current = Date.now() + SWIPE_PRESS_GUARD_MS;
  }, []);

  const openConversation = useCallback((item: MockConversation) => {
    const key = conversationRowKey(item);
    // 左滑松手后的合成 click：保持展开，方便点「收藏」
    if (Date.now() < swipeGuardUntilRef.current) return;
    // 已展开时再点 cell：只收起，不进房
    if (key && openRowKeyRef.current === key) {
      rowMapRef.current[key]?.closeRow();
      return;
    }
    if (openRowKeyRef.current) {
      rowMapRef.current[openRowKeyRef.current]?.closeRow();
    }
    prefetchConversationChatCache(item);
    router.push({
      pathname: '/chat/[id]',
      params: conversationChatRouteParams(item),
    } as unknown as Href);
  }, []);

  // 从收藏页返回时同步收藏态
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

  // 全局：会话全部置灰后 Store 会拉 duty/status 并广播，同步上班按钮
  useEffect(() => {
    if (isSupervisor) return;
    const off = subscribeDutyState((onDuty) => setOnDuty(onDuty));
    return off;
  }, [isSupervisor]);

  // 首次进入：先用本地缓存展示，claimed/list 与值班/收藏在后台同步
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        if (!(await waitForAuthBootstrap())) return;
        await ensureClaimedConversationsHydrated();
        const hasCache = getClaimedConversationsSnapshot().length > 0;
        if (alive && !hasCache) setLoading(true);
        else if (alive) setLoading(false);

        const st = await dutyStatus().catch(() => null);
        if (alive && st?.ok) {
          setOnDuty(st.on_duty);
          await saveDutyState(getAgentId(), st.on_duty).catch(() => {});
        } else {
          const persisted = await loadDutyState(getAgentId());
          if (alive) setOnDuty(persisted);
        }

        const fav = await listCollectedAudiences().catch(() => null);
        if (alive && fav?.ok && Array.isArray(fav.collected_audience_ids)) {
          setFavoritedKeys(
            new Set(fav.collected_audience_ids.map((id) => id.trim()).filter(Boolean)),
          );
        }

        await refreshClaimedConversations();
      } catch {
        // 网络失败：保留缓存/现状，避免清空
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, []);

  // 退出页面时清理刷新按钮冷却定时器
  useEffect(() => {
    return () => {
      if (refreshBtnCooldownTimerRef.current) clearTimeout(refreshBtnCooldownTimerRef.current);
    };
  }, []);

  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      // 点击右上角刷新：同时刷新 duty 状态与会话列表（列表刷新走全局 Store）
      const [st] = await Promise.all([
        dutyStatus().catch(() => null),
        refreshClaimedConversations(),
      ]);

      if (st?.ok) {
        setOnDuty(st.on_duty);
        await saveDutyState(getAgentId(), st.on_duty).catch(() => {});
      }
      await intake.refreshIntakeStatus();
      const fav = await listCollectedAudiences().catch(() => null);
      if (fav?.ok && Array.isArray(fav.collected_audience_ids)) {
        setFavoritedKeys(
          new Set(fav.collected_audience_ids.map((id) => id.trim()).filter(Boolean)),
        );
      }
    } catch {
      // 忽略错误，保留现状
    } finally {
      setRefreshing(false);
    }
  }, [intake.refreshIntakeStatus]);

  const startRefreshBtnCooldown = useCallback(() => {
    setRefreshBtnCooldown(true);
    if (refreshBtnCooldownTimerRef.current) clearTimeout(refreshBtnCooldownTimerRef.current);
    refreshBtnCooldownTimerRef.current = setTimeout(() => {
      setRefreshBtnCooldown(false);
      refreshBtnCooldownTimerRef.current = null;
    }, REFRESH_BTN_COOLDOWN_MS);
  }, []);

  /** 右上角刷新按钮：接口完成后 5 秒内不可再次点击 */
  const handleManualRefresh = useCallback(async () => {
    if (refreshing || refreshBtnCooldown) return;
    try {
      await handleRefresh();
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
  const hasActiveFilter = activeMajorId !== 'all' || activeSubId !== 'all';
  const bannerMode: ConnectionBannerMode | null = !isOnline
    ? 'offline'
    : connectionState === 'connection_timeout'
      ? 'timeout'
      : connectionState === 'reconnecting'
        ? 'reconnecting'
        : connectionState !== 'connected'
          ? 'connecting'
          : null;

  const list = useMemo(() => {
    const seen = new Set<string>();
    return conversations
      .filter((c) => matchesFilter(c, activeMajorId, activeSubId))
      .filter((c) => matchesConversationKeyword(c, keyword))
      .filter((c) => {
        const k = conversationRowKey(c);
        if (!k) return true;
        if (seen.has(k)) return false;
        seen.add(k);
        return true;
      });
  }, [keyword, activeMajorId, activeSubId, conversations]);

  const activeList = useMemo(
    () => list.filter((c) => !c.inactive && !!c.id?.trim()),
    [list],
  );
  const batch = useConversationListBatchActions(activeList);
  const { ackProcessed, isAckSubmitting } = useAckConversationPending();
  const headerSubtitle = batch.batchSelectMode
    ? batch.batchPreparing
      ? '正在准备默认选中…'
      : `已选 ${batch.selectedTaskIds.size} 个活跃会话`
    : formatConversationCountLabel(claimedCount, maxActiveCap);

  const [listMoreOpen, setListMoreOpen] = useState(false);
  const handleListMorePress = useCallback(() => {
    setListMoreOpen(true);
  }, []);
  const closeListMore = useCallback(() => setListMoreOpen(false), []);

  const handleAckProcessed = useCallback(
    (
      item: MockConversation,
      rowMap: { [key: string]: { closeRow: () => void } },
    ) => {
      const rowKey = conversationRowKey(item);
      rowMap[rowKey]?.closeRow();
      void ackProcessed(item);
    },
    [ackProcessed],
  );

  const handleToggleFavorite = useCallback(
    (
      item: MockConversation,
      rowMap: { [key: string]: { closeRow: () => void } },
    ) => {
      if (item.inactive) return;
      const rowKey = conversationRowKey(item);
      const audienceId = conversationFavoriteKey(item);
      if (!rowKey) return;
      rowMap[rowKey]?.closeRow();

      if (!audienceId) {
        appAlert('收藏失败', '缺少用户标识，无法收藏');
        return;
      }
      if (favoritingRef.current.has(audienceId)) return;

      const wasFavorited = favoritedKeys.has(audienceId);
      // 乐观更新
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
          // 失败回滚
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

  const handleDeleteInactive = useCallback(
    (
      item: MockConversation,
      rowMap: { [key: string]: { closeRow: () => void } },
    ) => {
      if (!item.inactive) return;
      const rowKey = conversationRowKey(item);
      if (rowKey) rowMap[rowKey]?.closeRow();

      const title =
        (item.audiencePlatformNickname || item.to || '').trim() || '该会话';
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
                  await clearChatMessagesCacheForConversations(
                    [imId],
                    'swipe_remove_inactive',
                  );
                }
              } catch (e) {
                appAlert('删除失败', e instanceof Error ? e.message : '请稍后重试');
              }
            })();
          },
        },
      ]);
    },
    [],
  );

  const applyDutyChange = useCallback(async (next: boolean) => {
    setOnDuty(next); // 乐观更新
    try {
      const res = next ? await dutyOn() : await dutyOff();
      setOnDuty(res.on_duty);
      await saveDutyState(getAgentId(), res.on_duty);

      // 上班：取消下班轮询，立即刷新一次会话列表
      if (res.on_duty) {
        cancelSyncClaimedListAfterDutyOff();
        void handleRefresh();
        return;
      }

      // 下班：短轮询 claimed/list 对账置灰（不依赖 eventType=2）
      void syncClaimedListAfterDutyOff({
        reclaimedTaskCount: 'reclaimedTaskCount' in res ? res.reclaimedTaskCount : undefined,
      });
    } catch (e) {
      setOnDuty(!next); // 失败回退
      appAlert(next ? '上班登记失败' : '下班登记失败', e instanceof Error ? e.message : '请稍后重试');
    }
  }, [handleRefresh]);

  const handleToggleDuty = useCallback(() => {
    const next = !onDuty;
    if (!next) {
      appAlert(
        '确认下班',
        '下班后，所有会话任务将被系统回收并重新分配，当前进行中的会话可能会分配给其他客服。确定下班吗？',
        [
          { text: '取消', style: 'cancel' },
          {
            text: '确认下班',
            style: 'destructive',
            onPress: () => {
              void applyDutyChange(false);
            },
          },
        ],
      );
      return;
    }
    void applyDutyChange(true);
  }, [onDuty, applyDutyChange]);

  const handleSelectMajor = (id: string) => {
    setActiveMajorId(id);
    setActiveSubId('all');
  };

  const handleSelectSub = (id: string) => {
    setActiveSubId(id);
  };

  const listKeyExtractor = useCallback(
    (item: MockConversation, index: number) => conversationRowKey(item) || `conv-${index}`,
    [],
  );

  const renderConversationRow = useCallback(
    ({ item }: { item: MockConversation }) => (
      <ConversationItem
        item={item}
        favorited={favoritedKeys.has(conversationFavoriteKey(item))}
        batchSelectMode={batch.batchSelectMode}
        batchChecked={
          !!(item.id ?? '').trim() && batch.selectedTaskIds.has((item.id ?? '').trim())
        }
        onPress={openConversation}
        onToggleBatch={batch.toggleBatchSelection}
      />
    ),
    [
      batch.batchSelectMode,
      batch.selectedTaskIds,
      batch.toggleBatchSelection,
      favoritedKeys,
      openConversation,
    ],
  );

  const getConversationItemLayout = useCallback(
    (_data: ArrayLike<MockConversation> | null | undefined, index: number) => ({
      length: CONVERSATION_ROW_HEIGHT,
      offset: CONVERSATION_ROW_HEIGHT * index,
      index,
    }),
    [],
  );

  const batchListExtraData = useMemo(
    () => ({
      batchPreparing: batch.batchPreparing,
      selectedTaskIds: batch.selectedTaskIds,
      favoritedKeys,
    }),
    [batch.batchPreparing, batch.selectedTaskIds, favoritedKeys],
  );

  const listContentContainerStyle = useMemo(
    () => [styles.listContent, list.length === 0 && styles.listContentEmpty],
    [list.length],
  );

  const listEmptyComponent = useMemo(
    () => (
      <View style={styles.empty}>
        <View style={styles.emptyTopSpacer} />
        <View style={[styles.emptyIcon, { backgroundColor: theme.surface2 }]}>
          <MessageOutlined size={50} color={theme.placeholder} />
        </View>
        <Text style={[styles.emptyText, { color: theme.textSubtle }]}>暂无会话</Text>
        <View style={styles.emptyBottomSpacer} />
      </View>
    ),
    [theme.placeholder, theme.surface2, theme.textSubtle],
  );

  return (
    <ScreenCanvas>
      <StatusBar style="dark" />
      <View style={styles.page}>
        <View style={styles.pageHeader}>
          <ScreenHeader
            title="聊天"
            subtitle={headerSubtitle}
            subtitleStyle={styles.listPaneSubtitle}
            titleAccessory={
              isSupervisor ? null : (
                <DutyStatusButton onDuty={onDuty} onToggle={handleToggleDuty} />
              )
            }
            right={(
              <View style={styles.headerRight}>
                <Pressable
                  onPress={handleManualRefresh}
                  disabled={refreshing || refreshBtnCooldown}
                  hitSlop={8}
                  style={({ pressed }) => [
                    styles.refreshBtn,
                    (refreshing || refreshBtnCooldown) && { opacity: 0.45 },
                    pressed && !refreshing && !refreshBtnCooldown && { opacity: 0.7, transform: [{ scale: 0.98 }] },
                  ]}
                  accessibilityRole="button"
                  accessibilityLabel="刷新会话列表"
                >
                  {refreshing ? (
                    <ActivityIndicator size={22} color={theme.text} />
                  ) : (
                    <ReloadOutlined
                      size={22}
                      color={refreshBtnCooldown ? theme.placeholder : theme.text}
                    />
                  )}
                </Pressable>
                {isSupervisor ? null : batch.batchSelectMode ? (
                  <>
                    <Pressable
                      onPress={batch.cancelBatchSelect}
                      disabled={batch.batchActionBusy}
                      hitSlop={8}
                      style={({ pressed }) => [
                        styles.batchHeaderCancelBtn,
                        batch.batchActionBusy && { opacity: 0.45 },
                        pressed && !batch.batchActionBusy && { opacity: 0.75 },
                      ]}
                      accessibilityRole="button"
                      accessibilityLabel="取消批量操作"
                    >
                      <Text style={[styles.batchHeaderCancelText, { color: theme.textMuted }]}>
                        取消
                      </Text>
                    </Pressable>
                    <Pressable
                      onPress={batch.confirmBatchAction}
                      disabled={batch.batchActionBusy || batch.batchPreparing}
                      hitSlop={8}
                      style={({ pressed }) => [
                        styles.batchHeaderBtn,
                        {
                          backgroundColor: batch.batchKind === 'transfer' ? theme.primary : theme.danger,
                          borderColor: batch.batchKind === 'transfer' ? theme.primary : theme.danger,
                        },
                        batch.batchActionBusy && { opacity: 0.55 },
                        pressed && !batch.batchActionBusy && { opacity: 0.88 },
                      ]}
                      accessibilityRole="button"
                      accessibilityLabel={batch.batchKind === 'transfer' ? '确定转移所选会话' : '确定结束所选会话'}
                    >
                      {batch.batchActionBusy ? (
                        <ActivityIndicator size="small" color="#FFFFFF" />
                      ) : (
                        <Text style={[styles.batchHeaderBtnText, { color: '#FFFFFF' }]}>
                          {batch.batchKind === 'transfer' ? '转移' : '确定结束'}
                        </Text>
                      )}
                    </Pressable>
                  </>
                ) : (
                  <Pressable
                    onPress={handleListMorePress}
                    hitSlop={8}
                    style={({ pressed }) => [pressed && { opacity: 0.7 }]}
                    accessibilityRole="button"
                    accessibilityLabel="更多操作"
                  >
                    <MoreOutlined size={22} color={theme.text} />
                  </Pressable>
                )}
              </View>
            )}
          />

          {/* 网络 / 连接状态提示 */}
          {bannerMode ? <ConnectionBanner mode={bannerMode} onRetry={retry} /> : null}

          <IntakeStatusBar {...intake} />

          {/* 搜索 + 筛选 */}
          <View style={styles.searchSection}>
            <View style={styles.searchRow}>
              <View style={[styles.searchBox, { backgroundColor: theme.surface, borderColor: theme.border }]}>
                <SearchInputGlyph size={17} color={theme.placeholder} />
                <TextInput
                  style={[styles.searchInput, { color: theme.text }]}
                  placeholder="搜索会话"
                  placeholderTextColor={theme.placeholder}
                  value={keyword}
                  onChangeText={setKeyword}
                />
              </View>
            </View>

            {filterOpen ? (
              <ChatFilterPanel
                majorFilters={MOCK_CHAT_MAJOR_FILTERS}
                subFilters={subFilters}
                activeMajorId={activeMajorId}
                activeSubId={activeSubId}
                majorUnreadMap={majorUnreadMap}
                subUnreadMap={subUnreadMap}
                onSelectMajor={handleSelectMajor}
                onSelectSub={handleSelectSub}
              />
            ) : null}
          </View>
        </View>

        {/* 会话列表：左右铺满 */}
        {loading && list.length === 0 ? (
          <View style={styles.loadingWrap}>
            <ActivityIndicator color={theme.primary} />
          </View>
        ) : batch.batchSelectMode ? (
          <FlatList
            style={styles.list}
            data={list}
            keyExtractor={listKeyExtractor}
            renderItem={renderConversationRow}
            extraData={batchListExtraData}
            getItemLayout={getConversationItemLayout}
            initialNumToRender={16}
            maxToRenderPerBatch={16}
            windowSize={21}
            removeClippedSubviews={false}
            contentContainerStyle={listContentContainerStyle}
            showsVerticalScrollIndicator={false}
            ListEmptyComponent={listEmptyComponent}
          />
        ) : (
          <SwipeListView
            style={styles.list}
            data={list}
            keyExtractor={listKeyExtractor}
            useFlatList
            closeOnRowPress={false}
            closeOnScroll
            closeOnRowOpen
            closeOnRowBeginSwipe
            disableRightSwipe={false}
            rightOpenValue={-SWIPE_ACTIVE_OPEN_WIDTH}
            swipeGestureBegan={markSwipeGuard}
            swipeGestureEnded={markSwipeGuard}
            onSwipeValueChange={(e) => {
              if (Math.abs(e.value) > 8) markSwipeGuard();
              const key = e.key;
              if (!key) return;
              const revealed = Math.abs(e.value) > 2;
              setSwipeRevealKeys((prev) => {
                const has = prev.has(key);
                if (revealed === has) return prev;
                const next = new Set(prev);
                if (revealed) next.add(key);
                else next.delete(key);
                return next;
              });
            }}
            renderItem={renderConversationRow}
            getItemLayout={getConversationItemLayout}
            initialNumToRender={16}
            maxToRenderPerBatch={16}
            windowSize={21}
            removeClippedSubviews={false}
            extraData={batchListExtraData}
            renderHiddenItem={(data, rowMap) => {
              const rowKey = conversationRowKey(data.item);
              const showAction = !!rowKey && swipeRevealKeys.has(rowKey);
              if (data.item.inactive) {
                return (
                  <View style={[styles.rowBack, { backgroundColor: theme.bg }]}>
                    {showAction ? (
                      <Pressable
                        style={[styles.swipeAction, { backgroundColor: '#EF4444' }]}
                        onPress={() => handleDeleteInactive(data.item, rowMap)}
                      >
                        <DeleteOutlined size={20} color="#FFF" />
                        <Text style={styles.swipeActionText}>删除</Text>
                      </Pressable>
                    ) : null}
                  </View>
                );
              }
              const favorited = favoritedKeys.has(conversationFavoriteKey(data.item));
              const showAck = canAckConversationPending(data.item);
              const ackSubmitting = isAckSubmitting(data.item.id ?? '');
              return (
                <View style={[styles.rowBack, { backgroundColor: theme.bg }]}>
                  {showAction ? (
                    <>
                      {showAck ? (
                        <Pressable
                          style={[styles.swipeAction, { backgroundColor: theme.primary }]}
                          onPress={() => handleAckProcessed(data.item, rowMap)}
                          disabled={ackSubmitting}
                        >
                          {ackSubmitting ? (
                            <ActivityIndicator size="small" color="#FFF" />
                          ) : (
                            <>
                              <CheckCircleOutlined size={20} color="#FFF" />
                              <Text style={styles.swipeActionText}>已处理</Text>
                            </>
                          )}
                        </Pressable>
                      ) : null}
                      <Pressable
                        style={[
                          styles.swipeAction,
                          { backgroundColor: favorited ? '#9CA3AF' : '#F5A623' },
                        ]}
                        onPress={() => handleToggleFavorite(data.item, rowMap)}
                      >
                        {favorited ? (
                          <StarFilled size={20} color="#FFF" style={{ color: '#FFF', fontSize: 20 }} />
                        ) : (
                          <StarOutlined size={20} color="#FFF" style={{ color: '#FFF', fontSize: 20 }} />
                        )}
                        <Text style={styles.swipeActionText}>
                          {favorited ? '取消收藏' : '收藏'}
                        </Text>
                      </Pressable>
                    </>
                  ) : null}
                </View>
              );
            }}
            onRowOpen={(rowKey, rowMap) => {
              markSwipeGuard();
              openRowKeyRef.current = rowKey;
              rowMapRef.current = rowMap;
              setSwipeRevealKeys((prev) => {
                if (prev.has(rowKey)) return prev;
                const next = new Set(prev);
                next.add(rowKey);
                return next;
              });
            }}
            onRowDidOpen={markSwipeGuard}
            onRowClose={(rowKey) => {
              if (openRowKeyRef.current === rowKey) openRowKeyRef.current = null;
              setSwipeRevealKeys((prev) => {
                if (!prev.has(rowKey)) return prev;
                const next = new Set(prev);
                next.delete(rowKey);
                return next;
              });
            }}
            contentContainerStyle={listContentContainerStyle}
            showsVerticalScrollIndicator={false}
            ListEmptyComponent={listEmptyComponent}
          />
        )}
      </View>
      <ConversationListMoreSheet
        visible={listMoreOpen}
        onClose={closeListMore}
        onBatchComplete={batch.startBatchComplete}
        onBatchTransfer={batch.startBatchTransfer}
        onFavorites={() => router.push('/feature/chat/my-favorites' as unknown as Href)}
      />
      <BatchCompleteConfirmModal {...batch.batchConfirmModalProps} />
      <TransferAgentPicker {...batch.transferPickerProps} />
    </ScreenCanvas>
  );
}

const styles = StyleSheet.create({
  page: {
    flex: 1,
    minHeight: 0,
    minWidth: 0,
  },
  pageHeader: {
    paddingHorizontal: Tokens.spacing[4],
  },
  list: {
    flex: 1,
    minHeight: 0,
    overflow: 'hidden',
  },
  statusBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'flex-start',
    gap: 6,
    height: 32,
    paddingHorizontal: 12,
    borderRadius: Tokens.radius.pill,
  },
  statusText: {
    fontSize: 13,
    fontWeight: '600',
  },
  searchSection: {
    gap: Tokens.spacing[3],
    marginBottom: Tokens.spacing[1],
  },
  batchHeaderCancelBtn: {
    height: 32,
    paddingHorizontal: 6,
    alignItems: 'center',
    justifyContent: 'center',
  },
  batchHeaderCancelText: {
    fontSize: 13,
    fontWeight: '500',
  },
  batchHeaderBtn: {
    height: 32,
    paddingHorizontal: 10,
    borderRadius: Tokens.radius.pill,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: StyleSheet.hairlineWidth,
  },
  batchHeaderBtnText: {
    fontSize: 13,
    fontWeight: '600',
  },
  batchCheck: {
    width: 20,
    height: 20,
    borderRadius: 10,
    borderWidth: StyleSheet.hairlineWidth,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: Tokens.spacing[2],
    flexShrink: 0,
  },
  convItemBatchSelected: {
    backgroundColor: 'rgba(90, 178, 172, 0.08)',
  },
  searchRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Tokens.spacing[3],
  },
  searchBox: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    gap: Tokens.spacing[2],
    height: 44,
    paddingHorizontal: Tokens.spacing[4],
    borderRadius: Tokens.radius.pill,
    borderWidth: StyleSheet.hairlineWidth,
  },
  searchInput: {
    flex: 1,
    fontSize: 15,
    padding: 0,
  },
  filterBtn: {
    width: 44,
    height: 44,
    borderRadius: 14,
    borderWidth: StyleSheet.hairlineWidth,
    alignItems: 'center',
    justifyContent: 'center',
  },
  headerRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Tokens.spacing[2],
  },
  refreshBtn: {
    width: 36,
    height: 32,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
  listContent: {
    paddingBottom: Tokens.spacing[4],
  },
  listContentEmpty: {
    flexGrow: 1,
  },
  loadingWrap: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
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
    width: 88,
    height: 88,
    borderRadius: 44,
    alignItems: 'center',
    justifyContent: 'center',
  },
  emptyText: {
    fontSize: 16,
  },
  convItem: {
    minWidth: 0,
    height: CONVERSATION_ROW_HEIGHT,
    justifyContent: 'center',
    paddingVertical: Tokens.spacing[3],
    paddingHorizontal: Tokens.spacing[4],
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  convItemInner: {
    flexDirection: 'row',
    alignItems: 'center',
    minWidth: 0,
  },
  convItemInnerMuted: {
    opacity: 0.55,
  },
  rowBack: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'stretch',
    justifyContent: 'flex-end',
    overflow: 'hidden',
  },
  swipeAction: {
    width: SWIPE_ACTION_WIDTH,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 4,
    alignSelf: 'stretch',
  },
  swipeActionText: {
    color: '#FFF',
    fontSize: 12,
    fontWeight: '600',
  },
  favoriteStar: {
    flexShrink: 0,
    marginLeft: 2,
  },
  avatarWrap: {
    position: 'relative',
    marginRight: Tokens.spacing[2],
  },
  avatar: {
    width: 44,
    height: 44,
    borderRadius: 22,
  },
  avatarImage: {
    width: '100%',
    height: '100%',
  },
  avatarFallback: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarFallbackText: {
    color: '#FFF',
    fontSize: 16,
    fontWeight: '600',
  },
  badge: {
    position: 'absolute',
    top: -4,
    right: -4,
    minWidth: 18,
    height: 18,
    borderRadius: 9,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 4,
  },
  badgeText: {
    color: '#fff',
    fontSize: 11,
    fontWeight: '700',
  },
  dotRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'flex-end',
  },
  dotCircle: {
    width: 16,
    height: 16,
    borderRadius: 8,
    borderWidth: 2,
    borderColor: '#fff',
  },
  /** 双点叠 1/3：后一个向左偏移直径的 1/3 */
  dotCircleOverlap: {
    marginLeft: -Math.round(16 / 3),
    zIndex: 1,
  },
  convBody: {
    flex: 1,
    minWidth: 0,
    marginRight: Tokens.spacing[2],
  },
  convTitleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Tokens.spacing[2],
    marginBottom: 2,
  },
  convTitle: {
    fontSize: ChatType.size.nameLabel,
    lineHeight: ChatType.lineHeight.nameLabel,
    fontWeight: ChatType.weight.regular,
    flex: 1,
    minWidth: 0,
    flexShrink: 1,
  },
  platformTag: {
    flexShrink: 0,
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: Tokens.radius.sm,
  },
  platformText: {
    fontSize: 11,
    fontWeight: '600',
  },
  convPreview: {
    fontSize: ChatType.size.subLabel,
    lineHeight: ChatType.lineHeight.subLabel,
    fontWeight: ChatType.weight.regular,
  },
  convTime: {
    flexShrink: 0,
    fontSize: ChatType.size.timestamp,
    lineHeight: ChatType.lineHeight.timestamp,
    fontWeight: ChatType.weight.regular,
    alignSelf: 'flex-end',
    marginTop: 0,
  },
  listPaneSubtitle: {
    fontSize: ChatType.size.pageSubtitle,
    lineHeight: ChatType.lineHeight.pageSubtitle,
    fontWeight: ChatType.weight.regular,
    color: ChatType.color.textDetail,
  },
  adoptionReviewBadge: {
    fontSize: 11,
    fontWeight: '600',
    color: ADOPTION_REVIEW_COLOR,
    lineHeight: 14,
  },
  convMeta: {
    flexShrink: 0,
    alignItems: 'flex-end',
    minWidth: 24,
    gap: 6,
  },
  /** 「AI复审」与状态点同一行：保证右侧列高度不超过头像，行高才能恒定 */
  convMetaBottom: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'flex-end',
    gap: 6,
    minHeight: 16,
  },
});
