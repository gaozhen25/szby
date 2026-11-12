// ============================================================
// 绩效核算 — 主管查看与核算下级标注员绩效
// ============================================================
import { useCallback, useMemo, useState } from 'react';
import {
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { StatusBar } from 'expo-status-bar';

import { ScreenCanvas } from '@/components/UI/ScreenCanvas';
import { ScreenHeader } from '@/components/UI/ScreenHeader';
import { FeatureUnderDevelopment } from '@/components/UI/FeatureUnderDevelopment';
import { useTheme } from '@/design/theme-context';
import { Tokens } from '@/design/tokens';
import {
  CalculatorOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  MessageOutlined,
  ThunderboltOutlined,
} from '@/ui/antd-icons';
import { useConfirmDialog } from '@/hooks/useConfirmDialog';
import { isProductionEnv } from '@/lib/api-host';
import {
  MOCK_SETTLEMENT_ITEMS,
  type MockSettlementItem,
  type SettlementStatus,
} from '@/mock/data';

type StatusFilter = 'all' | SettlementStatus;

const STATUS_FILTERS: { id: StatusFilter; label: string }[] = [
  { id: 'all', label: '全部' },
  { id: 'pending', label: '待核算' },
  { id: 'settled', label: '已核算' },
];

function formatMoney(value: number): string {
  const sign = value >= 0 ? '' : '-';
  return `${sign}¥${Math.abs(value).toFixed(2)}`;
}

function calcTotal(item: MockSettlementItem): number {
  return item.onlineSalary + item.replySalary - item.deduction;
}

function SummaryCard({
  pendingCount,
  pendingAmount,
  settledCount,
}: {
  pendingCount: number;
  pendingAmount: number;
  settledCount: number;
}) {
  const theme = useTheme();

  return (
    <View
      style={[
        styles.summaryCard,
        { backgroundColor: theme.primary },
        Tokens.shadow.card,
      ]}
    >
      <View pointerEvents="none" style={StyleSheet.absoluteFill}>
        <View style={[styles.summaryOrb, { backgroundColor: '#FFF', opacity: 0.08 }]} />
      </View>
      <View style={styles.summaryStats}>
        <View style={styles.summaryStat}>
          <Text style={styles.summaryStatValue} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.8}>
            {pendingCount}
          </Text>
          <Text style={styles.summaryStatLabel}>待核算</Text>
        </View>
        <View style={styles.summaryDivider} />
        <View style={styles.summaryStat}>
          <Text style={styles.summaryStatValue} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.7}>
            {formatMoney(pendingAmount)}
          </Text>
          <Text style={styles.summaryStatLabel}>待结金额</Text>
        </View>
        <View style={styles.summaryDivider} />
        <View style={styles.summaryStat}>
          <Text style={styles.summaryStatValue} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.8}>
            {settledCount}
          </Text>
          <Text style={styles.summaryStatLabel}>已核算</Text>
        </View>
      </View>
    </View>
  );
}

function FilterBar({
  filter,
  onChange,
}: {
  filter: StatusFilter;
  onChange: (next: StatusFilter) => void;
}) {
  const theme = useTheme();

  return (
    <View style={styles.filterRow}>
      {STATUS_FILTERS.map((item) => {
        const active = filter === item.id;
        return (
          <Pressable
            key={item.id}
            onPress={() => onChange(item.id)}
            style={({ pressed }) => [
              styles.filterChip,
              active
                ? { backgroundColor: theme.primarySoft, borderColor: theme.primary + '38' }
                : { backgroundColor: theme.surface, borderColor: theme.divider },
              pressed && { opacity: 0.88 },
            ]}
          >
            <Text
              style={[
                styles.filterChipText,
                { color: active ? theme.primary : theme.textSubtle },
                active && styles.filterChipTextActive,
              ]}
            >
              {item.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

function SettlementCard({
  item,
  onSettle,
}: {
  item: MockSettlementItem;
  onSettle: (item: MockSettlementItem) => void;
}) {
  const theme = useTheme();
  const total = calcTotal(item);
  const isPending = item.status === 'pending';
  const initial = item.annotatorName.trim().charAt(0) || 'A';

  return (
    <View
      style={[
        styles.card,
        { backgroundColor: theme.surface, borderColor: theme.border },
        Tokens.shadow.card,
      ]}
    >
      <View style={styles.cardTop}>
        <View style={styles.cardIdentity}>
          <View style={[styles.avatar, { backgroundColor: theme.primary }]}>
            <Text style={styles.avatarText}>{initial}</Text>
          </View>
          <View style={styles.cardIdentityBody}>
            <Text style={[styles.name, { color: theme.text }]}>{item.annotatorName}</Text>
            <Text style={[styles.period, { color: theme.textSubtle }]}>{item.periodLabel}</Text>
          </View>
        </View>
        <View
          style={[
            styles.statusBadge,
            {
              backgroundColor: isPending ? theme.warningSoft : theme.successSoft,
            },
          ]}
        >
          <Text
            style={[
              styles.statusText,
              { color: isPending ? theme.warning : theme.success },
            ]}
          >
            {isPending ? '待核算' : '已核算'}
          </Text>
        </View>
      </View>

      <View style={styles.metricsGrid}>
        <View style={styles.metricItem}>
          <ClockCircleOutlined size={14} color={theme.textSubtle} />
          <Text style={[styles.metricLabel, { color: theme.textSubtle }]}>在线时长</Text>
          <Text style={[styles.metricValue, { color: theme.text }]}>{item.onlineDuration}</Text>
        </View>
        <View style={styles.metricItem}>
          <MessageOutlined size={14} color={theme.textSubtle} />
          <Text style={[styles.metricLabel, { color: theme.textSubtle }]}>回复数</Text>
          <Text style={[styles.metricValue, { color: theme.text }]}>{item.replyCount}</Text>
        </View>
      </View>

      <View style={[styles.amountRow, { borderTopColor: theme.divider }]}>
        <View style={styles.amountItem}>
          <Text style={[styles.amountLabel, { color: theme.textSubtle }]}>在线工资</Text>
          <Text style={[styles.amountValue, { color: theme.primary }]}>
            {formatMoney(item.onlineSalary)}
          </Text>
        </View>
        <View style={styles.amountItem}>
          <Text style={[styles.amountLabel, { color: theme.textSubtle }]}>回复工资</Text>
          <Text style={[styles.amountValue, { color: theme.info }]}>
            {formatMoney(item.replySalary)}
          </Text>
        </View>
        <View style={styles.amountItem}>
          <Text style={[styles.amountLabel, { color: theme.textSubtle }]}>扣减</Text>
          <Text style={[styles.amountValue, { color: theme.danger }]}>
            {item.deduction > 0 ? `-${formatMoney(item.deduction).slice(1)}` : '¥0.00'}
          </Text>
        </View>
      </View>

      <View style={[styles.totalRow, { backgroundColor: theme.surface2 }]}>
        <Text style={[styles.totalLabel, { color: theme.text }]}>应结金额</Text>
        <Text style={[styles.totalValue, { color: theme.primary }]}>{formatMoney(total)}</Text>
      </View>

      {isPending ? (
        <Pressable
          style={({ pressed }) => [
            styles.settleBtn,
            { backgroundColor: theme.primary },
            pressed && { opacity: 0.85 },
          ]}
          onPress={() => onSettle(item)}
        >
          <CheckCircleOutlined size={18} color="#FFF" />
          <Text style={styles.settleBtnText}>确认核算</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

export default function PerformanceSettlementScreen() {
  if (isProductionEnv) {
    return (
      <FeatureUnderDevelopment
        title="绩效核算"
        subtitle="核算下级标注员的工作绩效与工资"
      />
    );
  }
  return <PerformanceSettlementScreenContent />;
}

function PerformanceSettlementScreenContent() {
  const theme = useTheme();
  const { confirm, ConfirmDialogHost } = useConfirmDialog();
  const [items, setItems] = useState(MOCK_SETTLEMENT_ITEMS);
  const [filter, setFilter] = useState<StatusFilter>('all');
  const [refreshing, setRefreshing] = useState(false);

  const summary = useMemo(() => {
    const pending = items.filter((i) => i.status === 'pending');
    const settled = items.filter((i) => i.status === 'settled');
    const pendingAmount = pending.reduce((sum, i) => sum + calcTotal(i), 0);
    return {
      pendingCount: pending.length,
      pendingAmount,
      settledCount: settled.length,
    };
  }, [items]);

  const filtered = useMemo(() => {
    if (filter === 'all') return items;
    return items.filter((i) => i.status === filter);
  }, [items, filter]);

  const handleSettle = useCallback((item: MockSettlementItem) => {
    const total = calcTotal(item);
    confirm({
      title: '确认核算',
      message: `确定核算「${item.annotatorName}」${item.periodLabel} 的绩效？应结金额 ${formatMoney(total)}`,
      confirmText: '确认核算',
      onConfirm: () => {
        setItems((prev) =>
          prev.map((i) =>
            i.id === item.id ? { ...i, status: 'settled' as const } : i,
          ),
        );
      },
    });
  }, [confirm]);

  const handleSettleAll = useCallback(() => {
    const pending = items.filter((i) => i.status === 'pending');
    if (pending.length === 0) return;

    const totalAmount = pending.reduce((sum, i) => sum + calcTotal(i), 0);
    confirm({
      title: '批量核算',
      message: `确定一键核算 ${pending.length} 条待核算记录？合计 ${formatMoney(totalAmount)}`,
      confirmText: '全部核算',
      onConfirm: () => {
        setItems((prev) =>
          prev.map((i) =>
            i.status === 'pending' ? { ...i, status: 'settled' as const } : i,
          ),
        );
      },
    });
  }, [confirm, items]);

  const handleRefresh = useCallback(() => {
    setRefreshing(true);
    // 接口就绪后替换为真实请求
    setTimeout(() => {
      setItems(MOCK_SETTLEMENT_ITEMS);
      setRefreshing(false);
    }, 800);
  }, []);

  return (
    <ScreenCanvas>
      <StatusBar style="dark" />
      <View style={styles.page}>
        <View style={styles.headerBlock}>
          <ScreenHeader
            embedded
            title="绩效核算"
            subtitle="核算下级标注员的工作绩效与工资"
          />

          <SummaryCard
            pendingCount={summary.pendingCount}
            pendingAmount={summary.pendingAmount}
            settledCount={summary.settledCount}
          />

          <View style={styles.toolbar}>
            <FilterBar filter={filter} onChange={setFilter} />
            {summary.pendingCount > 0 ? (
              <Pressable
                style={({ pressed }) => [
                  styles.batchBtn,
                  { backgroundColor: theme.primarySoft, borderColor: theme.primary + '30' },
                  pressed && { opacity: 0.85 },
                ]}
                onPress={handleSettleAll}
              >
                <ThunderboltOutlined size={15} color={theme.primary} />
                <Text style={[styles.batchBtnText, { color: theme.primary }]}>一键核算</Text>
              </Pressable>
            ) : null}
          </View>
        </View>

        <FlatList
          style={styles.list}
          contentContainerStyle={styles.listContent}
          data={filtered}
          keyExtractor={(item) => item.id}
          showsVerticalScrollIndicator={false}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={handleRefresh}
              tintColor={theme.primary}
              colors={[theme.primary]}
            />
          }
          renderItem={({ item }) => (
            <SettlementCard item={item} onSettle={handleSettle} />
          )}
          ItemSeparatorComponent={() => <View style={{ height: Tokens.spacing[3] }} />}
          ListEmptyComponent={
            <View style={styles.empty}>
              <CalculatorOutlined size={40} color={theme.placeholder} />
              <Text style={[styles.emptyText, { color: theme.textSubtle }]}>暂无核算记录</Text>
            </View>
          }
        />
      </View>
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
  list: { flex: 1 },
  listContent: {
    paddingBottom: Tokens.spacing[8],
  },

  summaryCard: {
    borderRadius: Tokens.radius.md,
    paddingHorizontal: Tokens.spacing[3],
    paddingVertical: Tokens.spacing[2] + 2,
    overflow: 'hidden',
  },
  summaryOrb: {
    position: 'absolute',
    top: -16,
    right: -8,
    width: 64,
    height: 64,
    borderRadius: 32,
  },
  summaryStats: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  summaryStat: {
    flex: 1,
    alignItems: 'center',
    gap: 2,
    minWidth: 0,
  },
  summaryStatValue: {
    fontSize: 16,
    fontWeight: '800',
    color: '#FFF',
    fontVariant: ['tabular-nums'],
  },
  summaryStatLabel: {
    fontSize: 10,
    color: 'rgba(255,255,255,0.75)',
    fontWeight: '500',
  },
  summaryDivider: {
    width: StyleSheet.hairlineWidth,
    height: 22,
    backgroundColor: 'rgba(255,255,255,0.25)',
  },

  toolbar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: Tokens.spacing[2],
  },
  filterRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: Tokens.spacing[2],
    flex: 1,
  },
  filterChip: {
    paddingHorizontal: Tokens.spacing[3],
    paddingVertical: Tokens.spacing[2],
    borderRadius: Tokens.radius.pill,
    borderWidth: StyleSheet.hairlineWidth,
  },
  filterChipText: {
    fontSize: 13,
    fontWeight: '500',
  },
  filterChipTextActive: {
    fontWeight: '600',
  },
  batchBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: Tokens.spacing[3],
    paddingVertical: Tokens.spacing[2],
    borderRadius: Tokens.radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    flexShrink: 0,
  },
  batchBtnText: {
    fontSize: 13,
    fontWeight: '600',
  },

  card: {
    borderRadius: Tokens.radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    padding: Tokens.spacing[4],
    gap: Tokens.spacing[3],
  },
  cardTop: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    gap: Tokens.spacing[2],
  },
  cardIdentity: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Tokens.spacing[3],
    flex: 1,
    minWidth: 0,
  },
  avatar: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarText: {
    fontSize: 16,
    fontWeight: '700',
    color: '#FFF',
  },
  cardIdentityBody: {
    flex: 1,
    gap: 2,
    minWidth: 0,
  },
  name: {
    fontSize: 16,
    fontWeight: '700',
  },
  period: {
    fontSize: 13,
  },
  statusBadge: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: Tokens.radius.pill,
  },
  statusText: {
    fontSize: 12,
    fontWeight: '600',
  },

  metricsGrid: {
    flexDirection: 'row',
    gap: Tokens.spacing[4],
  },
  metricItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  metricLabel: {
    fontSize: 12,
  },
  metricValue: {
    fontSize: 13,
    fontWeight: '600',
  },

  amountRow: {
    flexDirection: 'row',
    borderTopWidth: StyleSheet.hairlineWidth,
    paddingTop: Tokens.spacing[3],
  },
  amountItem: {
    flex: 1,
    alignItems: 'center',
    gap: 2,
  },
  amountLabel: {
    fontSize: 11,
  },
  amountValue: {
    fontSize: 14,
    fontWeight: '700',
    fontVariant: ['tabular-nums'],
  },

  totalRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: Tokens.spacing[3],
    paddingVertical: Tokens.spacing[3],
    borderRadius: Tokens.radius.md,
  },
  totalLabel: {
    fontSize: 14,
    fontWeight: '600',
  },
  totalValue: {
    fontSize: 18,
    fontWeight: '800',
    fontVariant: ['tabular-nums'],
  },

  settleBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    paddingVertical: Tokens.spacing[3],
    borderRadius: Tokens.radius.md,
  },
  settleBtnText: {
    fontSize: 15,
    fontWeight: '600',
    color: '#FFF',
  },

  empty: {
    alignItems: 'center',
    paddingVertical: Tokens.spacing[9],
    gap: Tokens.spacing[3],
  },
  emptyText: {
    fontSize: 14,
  },
});
