// ============================================================
// 标注员管理 — 主管查看与管理下级客服人员
// ============================================================
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Animated,
  FlatList,
  Keyboard,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  useWindowDimensions,
  View,
} from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { router } from 'expo-router';

import { ScreenCanvas } from '@/components/UI/ScreenCanvas';
import { ScreenHeader } from '@/components/UI/ScreenHeader';
import { useTheme } from '@/design/theme-context';
import { Tokens } from '@/design/tokens';
import {
  CheckCircleOutlined,
  EditOutlined,
  FileTextOutlined,
  InfoCircleOutlined,
  LogoutOutlined,
  ReloadOutlined,
  StopOutlined,
  TeamOutlined,
} from '@/ui/antd-icons';
import { useConfirmDialog } from '@/hooks/useConfirmDialog';
import {
  fetchSupervisorAgentsOverview,
  formatSupervisorApiError,
  supervisorForceAgentDutyOff,
  supervisorSetAgentValid,
} from '@/api/supervisor';
import { patchAdminAgent } from '@/api/agents';
import { waitForAuthBootstrap } from '@/core/auth-flow';
import { appAlert } from '@/lib/app-alert';
import { mapOverviewAgentsToAnnotators } from '@/lib/supervisor-agents';
import { type AnnotatorStatus, type MockAnnotator } from '@/mock/data';

const REFRESH_BTN_COOLDOWN_MS = 5000;

type StatusFilter = 'all' | AnnotatorStatus;

const STATUS_FILTERS: { id: StatusFilter; label: string }[] = [
  { id: 'all', label: '全部' },
  { id: 'online', label: '在线' },
  { id: 'offline', label: '离线' },
  { id: 'disabled', label: '已停用' },
];

function maskPhone(phone: string): string {
  if (phone.length < 7) return phone;
  return `${phone.slice(0, 3)}****${phone.slice(-4)}`;
}

function getStatusMeta(status: AnnotatorStatus, theme: ReturnType<typeof useTheme>) {
  switch (status) {
    case 'online':
      return { label: '在线', color: theme.success, bg: theme.successSoft, dot: theme.success };
    case 'offline':
      return { label: '离线', color: theme.textSubtle, bg: theme.surface2, dot: theme.placeholder };
    case 'disabled':
      return { label: '已停用', color: theme.danger, bg: theme.dangerSoft, dot: theme.danger };
  }
}

function StatusBadge({ status }: { status: AnnotatorStatus }) {
  const theme = useTheme();
  const meta = getStatusMeta(status, theme);

  return (
    <View style={[styles.statusBadge, { backgroundColor: meta.bg }]}>
      <View style={[styles.statusDot, { backgroundColor: meta.dot }]} />
      <Text style={[styles.statusText, { color: meta.color }]}>{meta.label}</Text>
    </View>
  );
}

function FilterBar({
  filter,
  counts,
  onChange,
}: {
  filter: StatusFilter;
  counts: Record<StatusFilter, number>;
  onChange: (next: StatusFilter) => void;
}) {
  const theme = useTheme();

  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.filterRow}
      decelerationRate="fast"
    >
      {STATUS_FILTERS.map((item) => {
        const active = filter === item.id;
        return (
          <Pressable
            key={item.id}
            onPress={() => onChange(item.id)}
            style={({ pressed }) => [
              styles.filterChip,
              active
                ? {
                    backgroundColor: theme.primarySoft,
                    borderColor: theme.primary + '45',
                    borderWidth: 1,
                  }
                : [
                    styles.filterChipIdle,
                    Tokens.shadow.card,
                    {
                      backgroundColor: theme.surface,
                      borderColor: theme.border,
                    },
                  ],
              pressed && { opacity: 0.88 },
            ]}
          >
            <Text
              style={[
                styles.filterChipText,
                { color: active ? theme.primaryPressed : theme.textMuted },
                active && styles.filterChipTextActive,
              ]}
            >
              {item.label}
            </Text>
            <Text
              style={[
                styles.filterChipCount,
                { color: active ? theme.primary : theme.text },
                active && styles.filterChipTextActive,
              ]}
            >
              {counts[item.id]}
            </Text>
          </Pressable>
        );
      })}
    </ScrollView>
  );
}

function AnnotatorCard({
  item,
  onViewSessions,
  onEditRemark,
  onForceOffline,
  onDisable,
  onEnable,
}: {
  item: MockAnnotator;
  onViewSessions: (annotator: MockAnnotator) => void;
  onEditRemark: (annotator: MockAnnotator) => void;
  onForceOffline: (annotator: MockAnnotator) => void;
  onDisable: (annotator: MockAnnotator) => void;
  onEnable: (annotator: MockAnnotator) => void;
}) {
  const theme = useTheme();
  const initial = item.name.trim().charAt(0) || 'A';
  const isDisabled = item.status === 'disabled';
  const isOnline = item.status === 'online';

  return (
    <Pressable
      onPress={() => onViewSessions(item)}
      style={({ pressed }) => [
        styles.card,
        { backgroundColor: theme.surface, borderColor: theme.border },
        Tokens.shadow.card,
        isDisabled && { opacity: 0.72 },
        pressed && { opacity: 0.94 },
      ]}
    >
      <View style={styles.cardHeader}>
        <View style={[styles.avatar, { backgroundColor: theme.primary }]}>
          <Text style={styles.avatarText}>{initial}</Text>
        </View>
        <View style={styles.cardHeaderBody}>
          <View style={styles.nameRow}>
            <Text style={[styles.name, { color: theme.text }]} numberOfLines={1}>
              {item.name}
            </Text>
            <StatusBadge status={item.status} />
          </View>
          <Text style={[styles.phone, { color: theme.textMuted }]}>
            {maskPhone(item.phone)}
          </Text>
        </View>
      </View>

      <View style={[styles.statsRow, { borderTopColor: theme.divider }]}>
        <View style={styles.statItem}>
          <Text style={[styles.statLabel, { color: theme.textSubtle }]}>在线时长</Text>
          <Text style={[styles.statValue, { color: theme.text }]}>{item.onlineDuration}</Text>
        </View>
        <View style={[styles.statSep, { backgroundColor: theme.divider }]} />
        <View style={styles.statItem}>
          <Text style={[styles.statLabel, { color: theme.textSubtle }]}>回复数</Text>
          <Text style={[styles.statValue, { color: theme.text }]}>{item.replyCount}</Text>
        </View>
        <View style={[styles.statSep, { backgroundColor: theme.divider }]} />
        <View style={styles.statItem}>
          <Text style={[styles.statLabel, { color: theme.textSubtle }]}>今日工资</Text>
          <Text style={[styles.statValue, { color: theme.primary }]}>{item.todaySalary}</Text>
        </View>
      </View>

      <View style={[styles.remarkRow, { backgroundColor: theme.surface2 }]}>
        <FileTextOutlined size={15} color={theme.textSubtle} />
        <Text style={[styles.remarkText, { color: theme.textMuted }]} numberOfLines={2}>
          {item.remark.trim() || '暂无备注'}
        </Text>
      </View>

      <Text style={[styles.lastActive, { color: theme.placeholder }]}>
        最近活跃：{item.lastActiveAt}
      </Text>

      <View style={styles.actionRow}>
        {isDisabled ? (
          <Pressable
            style={({ pressed }) => [
              styles.actionBtn,
              { backgroundColor: theme.primarySoft, borderColor: theme.primary + '30' },
              pressed && { opacity: 0.8 },
            ]}
            onPress={() => onEnable(item)}
          >
            <CheckCircleOutlined size={15} color={theme.primary} />
            <Text style={[styles.actionBtnText, { color: theme.primary }]}>启用账号</Text>
          </Pressable>
        ) : (
          <Pressable
            style={({ pressed }) => [
              styles.actionBtn,
              { backgroundColor: theme.primarySoft, borderColor: theme.primary + '30' },
              pressed && { opacity: 0.8 },
            ]}
            onPress={() => onEditRemark(item)}
          >
            <EditOutlined size={15} color={theme.primary} />
            <Text style={[styles.actionBtnText, { color: theme.primary }]}>修改备注</Text>
          </Pressable>
        )}

        {!isDisabled && isOnline ? (
          <Pressable
            style={({ pressed }) => [
              styles.actionBtn,
              { backgroundColor: theme.warningSoft, borderColor: theme.warning + '30' },
              pressed && { opacity: 0.8 },
            ]}
            onPress={() => onForceOffline(item)}
          >
            <LogoutOutlined size={15} color={theme.warning} />
            <Text style={[styles.actionBtnText, { color: theme.warning }]}>强制下班</Text>
          </Pressable>
        ) : null}

        {!isDisabled ? (
          <Pressable
            style={({ pressed }) => [
              styles.actionBtn,
              { backgroundColor: theme.dangerSoft, borderColor: theme.danger + '30' },
              pressed && { opacity: 0.8 },
            ]}
            onPress={() => onDisable(item)}
          >
            <StopOutlined size={15} color={theme.danger} />
            <Text style={[styles.actionBtnText, { color: theme.danger }]}>停用账号</Text>
          </Pressable>
        ) : null}
      </View>
    </Pressable>
  );
}

function RemarkModal({
  visible,
  annotator,
  onClose,
  onSave,
}: {
  visible: boolean;
  annotator: MockAnnotator | null;
  onClose: () => void;
  onSave: (id: string, remark: string) => void | Promise<void>;
}) {
  const theme = useTheme();
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);
  const { height: windowHeight } = useWindowDimensions();
  const [cardHeight, setCardHeight] = useState(0);
  const translateY = useRef(new Animated.Value(0)).current;

  const handleShow = useCallback(() => {
    setDraft(annotator?.remark ?? '');
    setSaving(false);
  }, [annotator?.remark]);

  useEffect(() => {
    const run = (toValue: number, duration = 180) => {
      Animated.timing(translateY, {
        toValue,
        duration,
        useNativeDriver: true,
      }).start();
    };

    // iOS 用 willChangeFrame：第三方键盘/候选栏高度变化时也能实时贴合（避免出现黑色间隙）
    const showEvent = Platform.OS === 'ios' ? 'keyboardWillChangeFrame' : 'keyboardDidShow';
    const hideEvent = Platform.OS === 'ios' ? 'keyboardWillHide' : 'keyboardDidHide';

    const showSub = Keyboard.addListener(showEvent, (e: any) => {
      const end = e?.endCoordinates;
      const duration = typeof e?.duration === 'number' ? e.duration : 180;

      // 优先使用键盘顶部的 screenY（更接近“实际可见键盘顶部”）
      // 目标：卡片底部 y == keyboardTopY（gap = 0）
      const keyboardTopY =
        typeof end?.screenY === 'number'
          ? end.screenY
          : windowHeight - (typeof end?.height === 'number' ? end.height : 0);

      const dy = keyboardTopY - (windowHeight / 2 + cardHeight / 2);
      run(dy, duration);
    });
    const hideSub = Keyboard.addListener(hideEvent, (e: any) => {
      const duration = typeof e?.duration === 'number' ? e.duration : 180;
      run(0, duration);
    });
    return () => {
      showSub.remove();
      hideSub.remove();
    };
  }, [cardHeight, translateY, windowHeight]);

  if (!annotator) return null;

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={onClose}
      onShow={handleShow}
    >
      <Pressable style={styles.modalOverlay} onPress={onClose}>
        <View style={styles.keyboardAvoid}>
          <Animated.View
            style={{ transform: [{ translateY }] }}
            onLayout={(e) => setCardHeight(e.nativeEvent.layout.height)}
          >
            <Pressable
              style={[styles.modalCard, { backgroundColor: theme.surface, borderColor: theme.border }]}
              onPress={(e) => e.stopPropagation()}
            >
              <Text style={[styles.modalTitle, { color: theme.text }]}>
                修改备注 · {annotator.name}
              </Text>
              <TextInput
                style={[
                  styles.remarkInput,
                  {
                    color: theme.text,
                    backgroundColor: theme.surface2,
                    borderColor: theme.border,
                  },
                ]}
                value={draft}
                onChangeText={setDraft}
                placeholder="输入备注信息，如班次、擅长类目等"
                placeholderTextColor={theme.placeholder}
                multiline
                maxLength={200}
                textAlignVertical="top"
              />
              <View style={styles.modalActions}>
                <Pressable
                  style={[styles.modalBtn, { backgroundColor: theme.surface2 }]}
                  onPress={onClose}
                  disabled={saving}
                >
                  <Text style={[styles.modalBtnText, { color: theme.textMuted }]}>取消</Text>
                </Pressable>
                <Pressable
                  style={[
                    styles.modalBtn,
                    { backgroundColor: theme.primary, opacity: saving ? 0.7 : 1 },
                  ]}
                  disabled={saving}
                  onPress={() => {
                    if (saving) return;
                    void (async () => {
                      setSaving(true);
                      try {
                        await onSave(annotator.id, draft.trim());
                        onClose();
                      } catch {
                        // 错误由 onSave 侧提示；保持弹窗便于重试
                      } finally {
                        setSaving(false);
                      }
                    })();
                  }}
                >
                  <Text style={[styles.modalBtnText, { color: '#FFF' }]}>
                    {saving ? '保存中…' : '保存'}
                  </Text>
                </Pressable>
              </View>
            </Pressable>
          </Animated.View>
        </View>
      </Pressable>
    </Modal>
  );
}

export default function AnnotatorsScreen() {
  const theme = useTheme();
  const { confirm, ConfirmDialogHost } = useConfirmDialog();
  const [annotators, setAnnotators] = useState<MockAnnotator[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState<StatusFilter>('all');
  const [editingAnnotator, setEditingAnnotator] = useState<MockAnnotator | null>(null);
  const remarksRef = useRef<Record<string, string>>({});
  const refreshBtnCooldownTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [refreshBtnCooldown, setRefreshBtnCooldown] = useState(false);

  const loadAnnotators = useCallback(async () => {
    const res = await fetchSupervisorAgentsOverview();
    if (!res.ok) return;
    const agents = res.agents ?? [];
    for (const a of agents) {
      const fromApi = a.additional_info?.trim();
      if (fromApi && !remarksRef.current[a.agent_id]?.trim()) {
        remarksRef.current[a.agent_id] = fromApi;
      }
    }
    setAnnotators(mapOverviewAgentsToAnnotators(agents, remarksRef.current));
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        await waitForAuthBootstrap();
        if (cancelled) return;
        await loadAnnotators();
      } catch (e) {
        console.warn('[annotators] overview failed', e);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [loadAnnotators]);

  useEffect(() => {
    return () => {
      if (refreshBtnCooldownTimerRef.current) clearTimeout(refreshBtnCooldownTimerRef.current);
    };
  }, []);

  const startRefreshBtnCooldown = useCallback(() => {
    setRefreshBtnCooldown(true);
    if (refreshBtnCooldownTimerRef.current) clearTimeout(refreshBtnCooldownTimerRef.current);
    refreshBtnCooldownTimerRef.current = setTimeout(() => {
      setRefreshBtnCooldown(false);
      refreshBtnCooldownTimerRef.current = null;
    }, REFRESH_BTN_COOLDOWN_MS);
  }, []);

  const handleRefresh = useCallback(async () => {
    if (refreshing) return;
    setRefreshing(true);
    try {
      await loadAnnotators();
    } catch (e) {
      console.warn('[annotators] refresh failed', e);
    } finally {
      setRefreshing(false);
    }
  }, [loadAnnotators, refreshing]);

  /** 右上角刷新按钮：接口完成后 5 秒内不可再次点击 */
  const handleManualRefresh = useCallback(async () => {
    if (refreshing || refreshBtnCooldown) return;
    try {
      await handleRefresh();
    } finally {
      startRefreshBtnCooldown();
    }
  }, [handleRefresh, refreshing, refreshBtnCooldown, startRefreshBtnCooldown]);

  const counts = useMemo(() => {
    const result: Record<StatusFilter, number> = {
      all: annotators.length,
      online: 0,
      offline: 0,
      disabled: 0,
    };
    for (const a of annotators) {
      result[a.status] += 1;
    }
    return result;
  }, [annotators]);

  const filtered = useMemo(() => {
    if (filter === 'all') return annotators;
    return annotators.filter((a) => a.status === filter);
  }, [annotators, filter]);

  const handleViewSessions = useCallback((annotator: MockAnnotator) => {
    const agentId = annotator.agentId ?? annotator.id;
    router.push({
      pathname: '/feature/annotators/[agentId]/sessions',
      params: { agentId, name: annotator.name },
    });
  }, []);

  const handleSaveRemark = useCallback(async (id: string, remark: string) => {
    try {
      const res = await patchAdminAgent(id, {
        additional_info: remark,
      });
      if (!res.ok) {
        appAlert('保存失败', '请稍后重试');
        throw new Error('保存失败');
      }
      remarksRef.current[id] = remark;
      setAnnotators((prev) =>
        prev.map((a) => (a.id === id ? { ...a, remark } : a)),
      );
    } catch (e) {
      if (!(e instanceof Error && e.message === '保存失败')) {
        appAlert('保存失败', e instanceof Error ? e.message : '请稍后重试');
      }
      throw e;
    }
  }, []);

  const handleForceOffline = useCallback((annotator: MockAnnotator) => {
    confirm({
      title: '强制下班',
      message: `确定将「${annotator.name}」强制下班？其当前持有的会话将被回收并重新分配，账号不会停用，对方可自行重新上班。`,
      confirmText: '确认下班',
      destructive: true,
      onConfirm: async () => {
        try {
          const res = await supervisorForceAgentDutyOff(annotator.agentId ?? annotator.id);
          if (!res.ok) {
            appAlert('强制下班失败', '请稍后重试');
            return;
          }
          const reclaimed = typeof res.reclaimedTaskCount === 'number' ? res.reclaimedTaskCount : 0;
          appAlert('已强制下班', `已强制「${annotator.name}」下班，回收任务 ${reclaimed} 个`);
          await handleRefresh();
        } catch (e) {
          appAlert('强制下班失败', formatSupervisorApiError(e));
        }
      },
    });
  }, [confirm, handleRefresh]);

  const handleDisable = useCallback((annotator: MockAnnotator) => {
    confirm({
      title: '停用标注员账号',
      message: `确定停用「${annotator.name}」的账号？停用后该标注员将无法登录系统，此操作需谨慎。`,
      confirmText: '确认停用',
      destructive: true,
      onConfirm: async () => {
        try {
          const res = await supervisorSetAgentValid(annotator.agentId ?? annotator.id, false);
          if (res.ok) {
            const reclaimed = typeof res.reclaimedTaskCount === 'number' ? res.reclaimedTaskCount : 0;
            const forced = res.forced_offline ? '，已强制下线' : '';
            appAlert('已停用账号', `已停用「${annotator.name}」账号，回收任务 ${reclaimed} 个${forced}`);
            await handleRefresh();
            return;
          }
          appAlert('停用失败', '请稍后重试');
        } catch (e) {
          appAlert('停用失败', e instanceof Error ? e.message : '请稍后重试');
        }
      },
    });
  }, [confirm, handleRefresh]);

  const handleEnable = useCallback((annotator: MockAnnotator) => {
    confirm({
      title: '启用标注员账号',
      message: `确定启用「${annotator.name}」的账号？启用后该标注员仍需自行上班才会参与自动领取。`,
      confirmText: '确认启用',
      destructive: false,
      onConfirm: async () => {
        try {
          const res = await supervisorSetAgentValid(annotator.agentId ?? annotator.id, true);
          if (res.ok) {
            appAlert('已启用账号', `已启用「${annotator.name}」账号`);
            await handleRefresh();
            return;
          }
          appAlert('启用失败', '请稍后重试');
        } catch (e) {
          appAlert('启用失败', e instanceof Error ? e.message : '请稍后重试');
        }
      },
    });
  }, [confirm, handleRefresh]);

  return (
    <ScreenCanvas>
      <StatusBar style="dark" />
      <View style={styles.page}>
        <View style={styles.headerBlock}>
          <ScreenHeader
            embedded
            title="标注员管理"
            subtitle={`管理下级客服人员，共 ${annotators.length} 人`}
            right={(
              <Pressable
                onPress={handleManualRefresh}
                disabled={refreshing || refreshBtnCooldown || loading}
                hitSlop={8}
                style={({ pressed }) => [
                  styles.refreshBtn,
                  (refreshing || refreshBtnCooldown || loading) && { opacity: 0.45 },
                  pressed && !refreshing && !refreshBtnCooldown && !loading && {
                    opacity: 0.7,
                    transform: [{ scale: 0.98 }],
                  },
                ]}
                accessibilityRole="button"
                accessibilityLabel="刷新标注员列表"
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
            )}
          />
          <FilterBar filter={filter} counts={counts} onChange={setFilter} />
          <View style={[styles.hintRow, { backgroundColor: theme.surface2 }]}>
            <InfoCircleOutlined size={15} color={theme.textSubtle} />
            <Text style={[styles.hintText, { color: theme.textSubtle }]}>
              点击标注员卡片可查看其正在进行的会话
            </Text>
          </View>
        </View>

        <FlatList
          style={styles.list}
          contentContainerStyle={styles.listContent}
          data={filtered}
          keyExtractor={(item) => item.id}
          showsVerticalScrollIndicator={false}
          refreshing={refreshing}
          onRefresh={handleRefresh}
          renderItem={({ item }) => (
            <AnnotatorCard
              item={item}
              onViewSessions={handleViewSessions}
              onEditRemark={setEditingAnnotator}
              onForceOffline={handleForceOffline}
              onDisable={handleDisable}
              onEnable={handleEnable}
            />
          )}
          ItemSeparatorComponent={() => <View style={{ height: Tokens.spacing[3] }} />}
          ListEmptyComponent={
            loading ? (
              <View style={styles.empty}>
                <ActivityIndicator size="large" color={theme.primary} />
                <Text style={[styles.emptyText, { color: theme.textSubtle }]}>加载中…</Text>
              </View>
            ) : (
              <View style={styles.empty}>
                <TeamOutlined size={40} color={theme.placeholder} />
                <Text style={[styles.emptyText, { color: theme.textSubtle }]}>暂无标注员</Text>
              </View>
            )
          }
        />
      </View>

      <RemarkModal
        visible={editingAnnotator !== null}
        annotator={editingAnnotator}
        onClose={() => setEditingAnnotator(null)}
        onSave={handleSaveRemark}
      />
      <ConfirmDialogHost />
    </ScreenCanvas>
  );
}

const styles = StyleSheet.create({
  page: {
    flex: 1,
    paddingHorizontal: Tokens.spacing[4],
  },
  headerBlock: {
    gap: Tokens.spacing[4],
    paddingTop: Tokens.spacing[2],
    paddingBottom: Tokens.spacing[3],
  },
  refreshBtn: {
    width: 36,
    height: 32,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
  hintRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Tokens.spacing[2],
    paddingHorizontal: Tokens.spacing[3],
    paddingVertical: Tokens.spacing[2],
    borderRadius: Tokens.radius.md,
  },
  hintText: {
    flex: 1,
    fontSize: 13,
    lineHeight: 18,
  },
  list: { flex: 1 },
  listContent: {
    paddingBottom: Tokens.spacing[8],
  },

  filterRow: {
    flexDirection: 'row',
    gap: Tokens.spacing[2],
    paddingRight: Tokens.spacing[1],
  },
  filterChip: {
    flexDirection: 'row',
    alignItems: 'center',
    flexShrink: 0,
    gap: 4,
    paddingHorizontal: Tokens.spacing[3],
    paddingVertical: Tokens.spacing[2],
    borderRadius: Tokens.radius.pill,
    borderWidth: StyleSheet.hairlineWidth,
  },
  filterChipIdle: {
    borderWidth: 1,
  },
  filterChipText: {
    fontSize: 13,
    fontWeight: '500',
    flexShrink: 0,
  },
  filterChipCount: {
    fontSize: 13,
    fontWeight: '600',
    fontVariant: ['tabular-nums'],
    flexShrink: 0,
  },
  filterChipTextActive: {
    fontWeight: '700',
  },

  card: {
    borderRadius: Tokens.radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    padding: Tokens.spacing[4],
    gap: Tokens.spacing[3],
  },
  cardHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Tokens.spacing[3],
  },
  avatar: {
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarText: {
    fontSize: 18,
    fontWeight: '700',
    color: '#FFF',
  },
  cardHeaderBody: {
    flex: 1,
    gap: 4,
    minWidth: 0,
  },
  nameRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: Tokens.spacing[2],
  },
  name: {
    fontSize: 16,
    fontWeight: '700',
    flex: 1,
  },
  phone: {
    fontSize: 13,
  },
  statusBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: Tokens.radius.pill,
  },
  statusDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
  },
  statusText: {
    fontSize: 11,
    fontWeight: '600',
  },

  statsRow: {
    flexDirection: 'row',
    alignItems: 'center',
    borderTopWidth: StyleSheet.hairlineWidth,
    paddingTop: Tokens.spacing[3],
  },
  statItem: {
    flex: 1,
    alignItems: 'center',
    gap: 2,
  },
  statSep: {
    width: StyleSheet.hairlineWidth,
    height: 28,
  },
  statLabel: {
    fontSize: 11,
  },
  statValue: {
    fontSize: 13,
    fontWeight: '700',
  },

  remarkRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: Tokens.spacing[2],
    padding: Tokens.spacing[3],
    borderRadius: Tokens.radius.md,
  },
  remarkText: {
    flex: 1,
    fontSize: 13,
    lineHeight: 18,
  },
  lastActive: {
    fontSize: 12,
    marginTop: -4,
  },

  actionRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: Tokens.spacing[2],
  },
  actionBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: Tokens.spacing[3],
    paddingVertical: Tokens.spacing[2],
    borderRadius: Tokens.radius.md,
    borderWidth: StyleSheet.hairlineWidth,
  },
  actionBtnText: {
    fontSize: 13,
    fontWeight: '600',
  },

  empty: {
    alignItems: 'center',
    paddingVertical: Tokens.spacing[9],
    gap: Tokens.spacing[3],
  },
  emptyText: {
    fontSize: 14,
  },

  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.45)',
    // 居中交给 keyboardAvoid 容器处理，避免 Android height 行为导致卡片下移
    paddingHorizontal: Tokens.spacing[5],
  },
  keyboardAvoid: {
    flex: 1,
    width: '100%',
    justifyContent: 'center',
  },
  modalCard: {
    borderRadius: Tokens.radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    padding: Tokens.spacing[5],
    gap: Tokens.spacing[4],
  },
  modalTitle: {
    fontSize: 17,
    fontWeight: '700',
  },
  remarkInput: {
    minHeight: 100,
    borderRadius: Tokens.radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    padding: Tokens.spacing[3],
    fontSize: 15,
    lineHeight: 22,
  },
  modalActions: {
    flexDirection: 'row',
    gap: Tokens.spacing[3],
  },
  modalBtn: {
    flex: 1,
    paddingVertical: Tokens.spacing[3],
    borderRadius: Tokens.radius.md,
    alignItems: 'center',
  },
  modalBtnText: {
    fontSize: 15,
    fontWeight: '600',
  },
});
