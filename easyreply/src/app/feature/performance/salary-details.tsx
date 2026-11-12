// ============================================================
// 工资明细 — 「墨韵青釉」
// ============================================================
import { useMemo, useState, type ComponentType } from 'react';
import {
  FlatList,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { router } from 'expo-router';

import { CustomNavBar } from '@/components/UI/CustomNavBar';
import { ScreenCanvas } from '@/components/UI/ScreenCanvas';
import { useTheme } from '@/design/theme-context';
import { Tokens } from '@/design/tokens';
import {
  CommentOutlined,
  FileTextOutlined,
  MinusCircleOutlined,
  WalletOutlined,
} from '@/ui/antd-icons';
import {
  MOCK_SALARY_DETAILS,
  type MockSalaryDetailItem,
  type SalaryDetailFilter,
  type SalaryDetailType,
} from '@/mock/data';

const FILTERS: SalaryDetailFilter[] = ['全部', '在线工资', '扣减额', '回复工资'];

interface TypePalette {
  bg: string;
  border: string;
  text: string;
  accent: string;
  icon: ComponentType<{ size?: number; color?: string }>;
}

function formatAmount(num: number): string {
  const abs = Math.abs(num);
  const [int, dec] = abs.toFixed(2).split('.');
  const sign = num >= 0 ? '+' : '-';
  return `${sign}¥${int}.${dec}`;
}

function formatPeriod(item: MockSalaryDetailItem): string {
  return `${item.periodStart} ~ ${item.periodEnd}`;
}

function getTypePalette(type: SalaryDetailType, theme: ReturnType<typeof useTheme>): TypePalette {
  switch (type) {
    case '在线工资':
      return {
        bg: theme.primarySoft,
        border: theme.primary + '45',
        text: theme.primaryPressed,
        accent: theme.primary,
        icon: WalletOutlined,
      };
    case '扣减额':
      return {
        bg: theme.dangerSoft,
        border: theme.danger + '40',
        text: theme.danger,
        accent: theme.danger,
        icon: MinusCircleOutlined,
      };
    case '回复工资':
      return {
        bg: theme.infoSoft,
        border: theme.info + '40',
        text: theme.info,
        accent: theme.info,
        icon: CommentOutlined,
      };
  }
}

function FilterChip({
  label,
  active,
  onPress,
}: {
  label: SalaryDetailFilter;
  active: boolean;
  onPress: () => void;
}) {
  const theme = useTheme();

  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [
        styles.chip,
        active
          ? {
              backgroundColor: theme.primarySoft,
              borderColor: theme.primary + '38',
            }
          : {
              backgroundColor: theme.surface2,
              borderColor: theme.divider,
            },
        pressed && { opacity: 0.88, transform: [{ scale: 0.98 }] },
      ]}
    >
      <Text
        style={[
          styles.chipText,
          { color: active ? theme.primary : theme.textSubtle },
          active && styles.chipTextActive,
        ]}
      >
        {label}
      </Text>
    </Pressable>
  );
}

function FilterBar({
  filter,
  onChange,
}: {
  filter: SalaryDetailFilter;
  onChange: (next: SalaryDetailFilter) => void;
}) {
  const theme = useTheme();

  return (
    <View style={[styles.filterPanel, { backgroundColor: theme.surface, borderColor: theme.border }]}>
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.chipScrollContent}
        decelerationRate="fast"
      >
        {FILTERS.map((item) => (
          <FilterChip
            key={item}
            label={item}
            active={filter === item}
            onPress={() => onChange(item)}
          />
        ))}
      </ScrollView>
    </View>
  );
}

function SummaryStrip({
  items,
}: {
  items: MockSalaryDetailItem[];
}) {
  const theme = useTheme();

  const income = items.filter((i) => i.amount > 0).reduce((s, i) => s + i.amount, 0);
  const deductions = items.filter((i) => i.amount < 0).reduce((s, i) => s + Math.abs(i.amount), 0);
  const net = income - deductions;

  return (
    <View style={[summaryStyles.card, { backgroundColor: theme.surface, borderColor: theme.border }]}>
      <View style={summaryStyles.statsRow}>
        <View style={summaryStyles.statItem}>
          <Text
            style={[summaryStyles.statLabel, { color: theme.textSubtle }]}
            numberOfLines={1}
          >
            收入¥
          </Text>
          <Text
            style={[summaryStyles.statValue, { color: theme.success }]}
            numberOfLines={1}
            adjustsFontSizeToFit
            minimumFontScale={0.75}
          >
            +{income.toFixed(0)}
          </Text>
        </View>
        <View style={[summaryStyles.statSep, { backgroundColor: theme.divider }]} />
        <View style={summaryStyles.statItem}>
          <Text
            style={[summaryStyles.statLabel, { color: theme.textSubtle }]}
            numberOfLines={1}
          >
            扣减¥
          </Text>
          <Text
            style={[summaryStyles.statValue, { color: theme.danger }]}
            numberOfLines={1}
            adjustsFontSizeToFit
            minimumFontScale={0.75}
          >
            -{deductions.toFixed(0)}
          </Text>
        </View>
        <View style={[summaryStyles.statSep, { backgroundColor: theme.divider }]} />
        <View style={summaryStyles.statItem}>
          <Text
            style={[summaryStyles.statLabel, { color: theme.textSubtle }]}
            numberOfLines={1}
          >
            净额¥
          </Text>
          <Text
            style={[
              summaryStyles.statValue,
              { color: net >= 0 ? theme.primaryPressed : theme.danger },
            ]}
            numberOfLines={1}
            adjustsFontSizeToFit
            minimumFontScale={0.75}
          >
            {net >= 0 ? '+' : '-'}{Math.abs(net).toFixed(0)}
          </Text>
        </View>
      </View>
    </View>
  );
}

const summaryStyles = StyleSheet.create({
  card: {
    marginHorizontal: Tokens.spacing[4],
    marginBottom: Tokens.spacing[3],
    borderRadius: Tokens.radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: Tokens.spacing[4],
    paddingVertical: Tokens.spacing[3],
  },
  statsRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  statItem: {
    flex: 1,
    minWidth: 0,
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: 2,
  },
  statSep: {
    width: StyleSheet.hairlineWidth,
    height: 28,
    flexShrink: 0,
  },
  statLabel: {
    width: '100%',
    textAlign: 'center',
    fontSize: 11,
    fontWeight: '500',
    letterSpacing: 0.1,
    flexShrink: 0,
  },
  statValue: {
    width: '100%',
    minWidth: 0,
    textAlign: 'center',
    fontSize: 15,
    fontWeight: '700',
    fontVariant: ['tabular-nums'],
    letterSpacing: -0.2,
  },
});

function SalaryDetailCard({ item }: { item: MockSalaryDetailItem }) {
  const theme = useTheme();
  const palette = getTypePalette(item.type, theme);
  const isNegative = item.amount < 0;
  const TypeIcon = palette.icon;

  return (
    <View style={[cardStyles.card, { backgroundColor: theme.surface, borderColor: theme.border }]}>
      <View style={[cardStyles.accent, { backgroundColor: palette.accent }]} />

      <View style={cardStyles.body}>
        <View style={cardStyles.top}>
          <Text
            style={[
              cardStyles.amount,
              { color: isNegative ? theme.danger : theme.text },
            ]}
            numberOfLines={1}
            adjustsFontSizeToFit
          >
            {formatAmount(item.amount)}
          </Text>
          <View style={[cardStyles.badge, { backgroundColor: palette.bg, borderColor: palette.border }]}>
            <TypeIcon size={12} color={palette.text} />
            <Text style={[cardStyles.badgeText, { color: palette.text }]}>{item.type}</Text>
          </View>
        </View>

        <View style={cardStyles.meta}>
          <View style={cardStyles.metaRow}>
            <Text style={[cardStyles.metaLabel, { color: theme.textSubtle }]}>周期</Text>
            <Text style={[cardStyles.metaValue, { color: theme.text }]} numberOfLines={1}>
              {formatPeriod(item)}
            </Text>
          </View>
          <View style={[cardStyles.metaDivider, { backgroundColor: theme.divider }]} />
          <View style={cardStyles.metaRow}>
            <Text style={[cardStyles.metaLabel, { color: theme.textSubtle }]}>入账</Text>
            <Text style={[cardStyles.metaValue, { color: theme.text }]} numberOfLines={1}>
              {item.creditedAt}
            </Text>
          </View>
        </View>
      </View>
    </View>
  );
}

const cardStyles = StyleSheet.create({
  card: {
    marginHorizontal: Tokens.spacing[4],
    marginBottom: Tokens.spacing[3],
    borderRadius: Tokens.radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    flexDirection: 'row',
    overflow: 'hidden',
  },
  accent: {
    width: 3,
  },
  body: {
    flex: 1,
    paddingHorizontal: Tokens.spacing[4],
    paddingVertical: Tokens.spacing[3],
    gap: Tokens.spacing[3],
  },
  top: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: Tokens.spacing[2],
  },
  amount: {
    fontSize: 22,
    fontWeight: '800',
    letterSpacing: -0.4,
    fontVariant: ['tabular-nums'],
    flex: 1,
  },
  badge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: Tokens.radius.pill,
    borderWidth: StyleSheet.hairlineWidth,
  },
  badgeText: {
    fontSize: 11,
    fontWeight: '600',
    letterSpacing: 0.1,
  },
  meta: {
    borderRadius: Tokens.radius.sm,
    overflow: 'hidden',
  },
  metaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Tokens.spacing[3],
    paddingVertical: 6,
  },
  metaLabel: {
    fontSize: 12,
    fontWeight: '500',
    width: 32,
    letterSpacing: 0.2,
  },
  metaValue: {
    flex: 1,
    fontSize: 13,
    fontWeight: '500',
    lineHeight: 18,
  },
  metaDivider: {
    height: StyleSheet.hairlineWidth,
  },
});

function EmptyState({ filter }: { filter: SalaryDetailFilter }) {
  const theme = useTheme();

  return (
    <View style={styles.emptyWrap}>
      <View style={[styles.emptyIcon, { backgroundColor: theme.surface2 }]}>
        <FileTextOutlined size={32} color={theme.placeholder} />
      </View>
      <Text style={[styles.emptyTitle, { color: theme.textMuted }]}>
        暂无{filter === '全部' ? '' : filter}记录
      </Text>
      <Text style={[styles.emptyHint, { color: theme.textSubtle }]}>
        试试切换筛选条件
      </Text>
    </View>
  );
}

export default function SalaryDetailsScreen() {
  const theme = useTheme();
  const [filter, setFilter] = useState<SalaryDetailFilter>('全部');

  const filteredItems = useMemo(() => {
    if (filter === '全部') return MOCK_SALARY_DETAILS;
    return MOCK_SALARY_DETAILS.filter((item) => item.type === filter);
  }, [filter]);

  const total = filteredItems.length;

  return (
    <ScreenCanvas safeAreaTop={false}>
      <StatusBar style="dark" />
      <CustomNavBar title="工资明细" onBack={() => router.back()} />

      <FilterBar filter={filter} onChange={setFilter} />

      {total > 0 ? <SummaryStrip items={filteredItems} /> : null}

      <FlatList
        style={styles.list}
        data={filteredItems}
        keyExtractor={(item) => item.id}
        showsVerticalScrollIndicator={false}
        contentContainerStyle={[
          styles.listContent,
          total === 0 && styles.listContentEmpty,
        ]}
        renderItem={({ item }) => <SalaryDetailCard item={item} />}
        ListEmptyComponent={<EmptyState filter={filter} />}
        ListFooterComponent={
          total > 0 ? (
            <Text style={[styles.footer, { color: theme.placeholder }]}>
              已加载全部 {total} 条
            </Text>
          ) : null
        }
      />
    </ScreenCanvas>
  );
}

const styles = StyleSheet.create({
  list: { flex: 1 },
  listContent: {
    paddingBottom: Tokens.spacing[8],
  },
  listContentEmpty: { flexGrow: 1 },
  filterPanel: {
    marginHorizontal: Tokens.spacing[4],
    marginTop: Tokens.spacing[2],
    marginBottom: Tokens.spacing[3],
    borderRadius: Tokens.radius.md,
    borderWidth: StyleSheet.hairlineWidth,
  },
  chipScrollContent: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Tokens.spacing[2],
    paddingHorizontal: Tokens.spacing[3],
    paddingVertical: Tokens.spacing[3],
  },
  chip: {
    minHeight: 28,
    paddingHorizontal: 11,
    paddingVertical: 4,
    borderRadius: Tokens.radius.pill,
    borderWidth: StyleSheet.hairlineWidth,
    justifyContent: 'center',
  },
  chipText: {
    fontSize: 12,
    fontWeight: '500',
    letterSpacing: 0.1,
  },
  chipTextActive: {
    fontWeight: '600',
  },
  footer: {
    textAlign: 'center',
    fontSize: 12,
    lineHeight: 18,
    marginTop: Tokens.spacing[2],
    letterSpacing: 0.2,
    fontWeight: '500',
  },
  emptyWrap: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingTop: Tokens.spacing[8],
    paddingBottom: Tokens.spacing[8],
  },
  emptyIcon: {
    width: 64,
    height: 64,
    borderRadius: 32,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: Tokens.spacing[3],
  },
  emptyTitle: {
    fontSize: 15,
    fontWeight: '600',
    letterSpacing: 0.1,
  },
  emptyHint: {
    fontSize: 13,
    marginTop: Tokens.spacing[2],
  },
});
