// ============================================================
// 绩效中心 — 「墨韵青釉」仪表盘
// ============================================================
import { useCallback, useState, type ComponentType } from 'react';
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { router } from 'expo-router';

import { FeatureUnderDevelopment } from '@/components/UI/FeatureUnderDevelopment';
import { ScreenCanvas } from '@/components/UI/ScreenCanvas';
import { ScreenHeader } from '@/components/UI/ScreenHeader';
import { useTheme } from '@/design/theme-context';
import { Tokens } from '@/design/tokens';
import { MOCK_PERFORMANCE, type MockPerformanceStats } from '@/mock/data';
import { isProductionEnv } from '@/lib/api-host';
import {
  ClockCircleOutlined,
  DownCircleOutlined,
  EyeInvisibleOutlined,
  EyeOutlined,
  InfoCircleOutlined,
  MessageOutlined,
  MinusCircleOutlined,
  ProfileOutlined,
  ReloadOutlined,
  RightOutlined,
} from '@/ui/antd-icons';

type MetricCellData = {
  icon: ComponentType<{ size?: number; color?: string }>;
  label: string;
  value: string;
  bg: string;
  iconBg: string;
  iconColor: string;
  valueColor?: string;
};

function maskMoney(value: string, visible: boolean): string {
  if (visible) return value;
  return value.includes('¥') ? '¥****' : '****';
}

function maskCount(value: string, visible: boolean): string {
  if (visible) return value;
  return value.replace(/\d/g, '*');
}

function MetricCell({
  icon: Icon,
  label,
  value,
  bg,
  iconBg,
  iconColor,
  valueColor,
}: MetricCellData) {
  const theme = useTheme();

  return (
    <View style={[styles.metricCell, { backgroundColor: bg, borderColor: iconColor + '28' }]}>
      <View style={[styles.metricIcon, { backgroundColor: iconBg }]}>
        <Icon size={17} color={iconColor} />
      </View>
      <View style={styles.metricText}>
        <Text style={[styles.metricLabel, { color: theme.textSubtle }]}>{label}</Text>
        <Text
          style={[styles.metricValue, { color: valueColor ?? theme.text }]}
          numberOfLines={2}
        >
          {value}
        </Text>
      </View>
    </View>
  );
}

function todayLabel(): string {
  const d = new Date();
  const weekdays = ['日', '一', '二', '三', '四', '五', '六'];
  return `${d.getMonth() + 1} 月 ${d.getDate()} 日 · 周${weekdays[d.getDay()]}`;
}

function DashboardCard({
  stats,
  refreshing,
  amountVisible,
  onToggleAmountVisible,
  onRefresh,
  onOpenDetails,
}: {
  stats: MockPerformanceStats;
  refreshing: boolean;
  amountVisible: boolean;
  onToggleAmountVisible: () => void;
  onRefresh: () => void;
  onOpenDetails: () => void;
}) {
  const theme = useTheme();

  const row1: MetricCellData[] = [
    {
      icon: ClockCircleOutlined,
      label: '在线时长',
      value: stats.onlineDuration,
      bg: theme.primarySoft,
      iconBg: theme.surface,
      iconColor: theme.primary,
    },
    {
      icon: MessageOutlined,
      label: '回复数',
      value: maskCount(`${stats.replyCount} 条`, amountVisible),
      bg: stats.replyCount > 0 ? theme.successSoft : theme.wash2,
      iconBg: theme.surface,
      iconColor: stats.replyCount > 0 ? theme.success : theme.textMuted,
      valueColor: stats.replyCount > 0 ? theme.success : theme.text,
    },
  ];

  const row2: MetricCellData[] = [
    {
      icon: MinusCircleOutlined,
      label: '扣减额',
      value: maskMoney(stats.deduction, amountVisible),
      bg: theme.dangerSoft,
      iconBg: theme.surface,
      iconColor: theme.danger,
      valueColor: theme.danger,
    },
    {
      icon: DownCircleOutlined,
      label: '已提现',
      value: maskMoney(stats.withdrawn, amountVisible),
      bg: theme.infoSoft,
      iconBg: theme.surface,
      iconColor: theme.info,
    },
  ];

  return (
    <View
      style={[
        styles.dashboard,
        { backgroundColor: theme.surface, borderColor: theme.border },
        Tokens.shadow.float,
      ]}
    >
      {/* 工资区：深色青釉底 */}
      <View style={[styles.salaryZone, { backgroundColor: theme.primary }]}>
        <View pointerEvents="none" style={StyleSheet.absoluteFill}>
          <View style={[styles.salaryOrb, { backgroundColor: '#FFF', opacity: 0.08 }]} />
          <View style={[styles.salaryOrb2, { backgroundColor: theme.wash1, opacity: 0.25 }]} />
        </View>

        <View style={styles.salaryTop}>
          <View style={styles.salaryTopLeft}>
            <Text style={styles.salaryDate}>{todayLabel()}</Text>
          </View>
          <Pressable
            style={styles.salaryActionBtn}
            onPress={onRefresh}
            disabled={refreshing}
            hitSlop={8}
            accessibilityRole="button"
            accessibilityLabel="刷新"
          >
            {refreshing ? (
              <ActivityIndicator size="small" color="#FFF" />
            ) : (
              <ReloadOutlined size={20} color="#FFF" />
            )}
          </Pressable>
        </View>

        <View style={styles.salaryAmountRow}>
          <Text style={styles.salaryAmount}>{maskMoney(stats.salary, amountVisible)}</Text>
          <Pressable
            style={styles.salaryEyeBtn}
            onPress={onToggleAmountVisible}
            hitSlop={8}
            accessibilityRole="button"
            accessibilityLabel={amountVisible ? '隐藏金额' : '显示金额'}
          >
            {amountVisible ? (
              <EyeOutlined size={22} color="rgba(255,255,255,0.9)" />
            ) : (
              <EyeInvisibleOutlined size={22} color="rgba(255,255,255,0.9)" />
            )}
          </Pressable>
        </View>
        <Text style={styles.salaryHint}>
          今日工资 · 可提现 {maskMoney(stats.withdrawable, amountVisible)}
        </Text>
      </View>

      {/* 指标 2×2：图标 + 右侧文字 */}
      <View style={styles.metrics}>
        <View style={styles.metricsRow}>
          {row1.map((cell) => (
            <MetricCell key={cell.label} {...cell} />
          ))}
        </View>
        <View style={styles.metricsRow}>
          {row2.map((cell) => (
            <MetricCell key={cell.label} {...cell} />
          ))}
        </View>
      </View>

      {/* 明细入口 */}
      <Pressable
        style={({ pressed }) => [
          styles.detailLink,
          { borderTopColor: theme.divider },
          pressed && { opacity: 0.75 },
        ]}
        onPress={onOpenDetails}
      >
        <View style={styles.detailLinkLeft}>
          <ProfileOutlined size={18} color={theme.primary} />
          <Text style={[styles.detailLinkText, { color: theme.text }]}>工资明细</Text>
        </View>
        <RightOutlined size={18} color={theme.placeholder} />
      </Pressable>
    </View>
  );
}

function TipCard() {
  const theme = useTheme();

  return (
    <View
      style={[
        styles.tipCard,
        { backgroundColor: theme.infoSoft, borderColor: theme.info + '30' },
      ]}
    >
      <InfoCircleOutlined size={18} color={theme.info} />
      <Text style={[styles.tipText, { color: theme.textMuted }]}>
        工资按在线时长与回复质量结算，扣减记录可在明细中查看。
      </Text>
    </View>
  );
}

export default function PerformanceScreen() {
  if (isProductionEnv) {
    return (
      <FeatureUnderDevelopment
        title="绩效中心"
        subtitle="实时查看今日工作表现与收入"
      />
    );
  }
  return <PerformanceScreenContent />;
}

function PerformanceScreenContent() {
  const [refreshing, setRefreshing] = useState(false);
  const [amountVisible, setAmountVisible] = useState(true);
  const stats = MOCK_PERFORMANCE;

  const handleRefresh = useCallback(() => {
    setRefreshing(true);
    setTimeout(() => setRefreshing(false), 800);
  }, []);

  return (
    <ScreenCanvas>
      <StatusBar style="dark" />
      <ScrollView
        style={styles.page}
        contentContainerStyle={styles.pageContent}
        showsVerticalScrollIndicator={false}
      >
        <ScreenHeader
          embedded
          title="绩效中心"
          subtitle="实时查看今日工作表现与收入"
        />

        <DashboardCard
          stats={stats}
          refreshing={refreshing}
          amountVisible={amountVisible}
          onToggleAmountVisible={() => setAmountVisible((v) => !v)}
          onRefresh={handleRefresh}
          onOpenDetails={() => router.push('/feature/performance/salary-details')}
        />

        <TipCard />
      </ScrollView>
    </ScreenCanvas>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1 },
  pageContent: {
    paddingHorizontal: Tokens.spacing[4],
    paddingTop: Tokens.spacing[2],
    paddingBottom: Tokens.spacing[8],
    gap: Tokens.spacing[5],
  },

  dashboard: {
    borderRadius: Tokens.radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    overflow: 'hidden',
  },

  salaryZone: {
    paddingHorizontal: Tokens.spacing[5],
    paddingTop: Tokens.spacing[5],
    paddingBottom: Tokens.spacing[6],
    overflow: 'hidden',
  },
  salaryOrb: {
    position: 'absolute',
    top: -30,
    right: -20,
    width: 120,
    height: 120,
    borderRadius: 60,
  },
  salaryOrb2: {
    position: 'absolute',
    bottom: -40,
    left: -30,
    width: 100,
    height: 100,
    borderRadius: 50,
  },
  salaryTop: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
  },
  salaryTopLeft: {
    flex: 1,
    minWidth: 0,
    paddingRight: Tokens.spacing[2],
  },
  salaryDate: {
    fontSize: 13,
    fontWeight: '600',
    color: 'rgba(255,255,255,0.85)',
    marginTop: 4,
    flexShrink: 1,
  },
  salaryActionBtn: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: 'rgba(255,255,255,0.15)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  salaryAmountRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Tokens.spacing[2],
  },
  salaryEyeBtn: {
    padding: Tokens.spacing[1],
    marginBottom: 4,
  },
  salaryAmount: {
    fontSize: 40,
    fontWeight: '800',
    color: '#FFF',
    letterSpacing: -1,
    fontVariant: ['tabular-nums'],
  },
  salaryHint: {
    fontSize: 14,
    color: 'rgba(255,255,255,0.75)',
    marginTop: Tokens.spacing[2],
    fontWeight: '500',
  },

  metrics: {
    padding: Tokens.spacing[3],
    gap: Tokens.spacing[2],
  },
  metricsRow: {
    flexDirection: 'row',
    gap: Tokens.spacing[2],
  },
  metricCell: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    gap: Tokens.spacing[2],
    borderRadius: Tokens.radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: Tokens.spacing[3],
    paddingVertical: Tokens.spacing[3],
    minHeight: 68,
  },
  metricIcon: {
    width: 34,
    height: 34,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  },
  metricText: {
    flex: 1,
    gap: 2,
    minWidth: 0,
  },
  metricLabel: {
    fontSize: 12,
    fontWeight: '500',
  },
  metricValue: {
    fontSize: 14,
    fontWeight: '700',
    letterSpacing: -0.2,
    lineHeight: 18,
  },

  detailLink: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: Tokens.spacing[4],
    paddingVertical: Tokens.spacing[4],
    borderTopWidth: StyleSheet.hairlineWidth,
  },
  detailLinkLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Tokens.spacing[2],
  },
  detailLinkText: {
    fontSize: 15,
    fontWeight: '600',
  },

  tipCard: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: Tokens.spacing[2],
    padding: Tokens.spacing[4],
    borderRadius: Tokens.radius.md,
    borderWidth: StyleSheet.hairlineWidth,
  },
  tipText: {
    flex: 1,
    fontSize: 13,
    lineHeight: 19,
  },
});
