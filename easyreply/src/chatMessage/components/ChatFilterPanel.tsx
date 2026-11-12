// ============================================================
// 会话列表 — 大类 / 小类双行筛选面板
// ============================================================
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { useTheme } from '@/design/theme-context';
import { Tokens } from '@/design/tokens';
import type { ChatFilterOption } from '@/mock/data';

const BADGE = {
  bg: '#D4565F',
  text: '#FFFFFF',
} as const;

type Props = {
  majorFilters: ChatFilterOption[];
  subFilters: ChatFilterOption[];
  activeMajorId: string;
  activeSubId: string;
  majorUnreadMap: Record<string, number>;
  subUnreadMap: Record<string, number>;
  onSelectMajor: (id: string) => void;
  onSelectSub: (id: string) => void;
};

function FilterChip({
  label,
  active,
  unread,
  onPress,
}: {
  label: string;
  active: boolean;
  unread: number;
  onPress: () => void;
}) {
  const theme = useTheme();
  const badgeRing = active ? theme.wash1 : theme.surface2;

  return (
    <View style={styles.chipOuter}>
      <Pressable
        onPress={onPress}
        style={({ pressed }) => [
          styles.chip,
          active
            ? { backgroundColor: theme.wash1, borderColor: theme.primary + '55' }
            : { backgroundColor: theme.surface2, borderColor: theme.border },
          pressed && { opacity: 0.88, transform: [{ scale: 0.98 }] },
        ]}
      >
        <Text
          style={[
            styles.chipText,
            { color: active ? theme.primaryPressed : theme.textMuted },
            active && styles.chipTextActive,
          ]}
        >
          {label}
        </Text>
      </Pressable>

      {unread > 0 ? (
        <View style={[styles.badge, { backgroundColor: BADGE.bg, borderColor: badgeRing }]}>
          <Text style={styles.badgeText}>{unread > 99 ? '99+' : unread}</Text>
        </View>
      ) : null}
    </View>
  );
}

function FilterRow({
  filters,
  activeId,
  unreadMap,
  onSelect,
}: {
  filters: ChatFilterOption[];
  activeId: string;
  unreadMap: Record<string, number>;
  onSelect: (id: string) => void;
}) {
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.chipRow}
    >
      {filters.map((filter) => (
        <FilterChip
          key={filter.id}
          label={filter.label}
          active={activeId === filter.id}
          unread={unreadMap[filter.id] ?? 0}
          onPress={() => onSelect(filter.id)}
        />
      ))}
    </ScrollView>
  );
}

export function ChatFilterPanel({
  majorFilters,
  subFilters,
  activeMajorId,
  activeSubId,
  majorUnreadMap,
  subUnreadMap,
  onSelectMajor,
  onSelectSub,
}: Props) {
  const theme = useTheme();

  return (
    <View
      style={[
        styles.panel,
        { backgroundColor: theme.surface, borderColor: theme.border },
      ]}
    >
      <FilterRow
        filters={majorFilters}
        activeId={activeMajorId}
        unreadMap={majorUnreadMap}
        onSelect={onSelectMajor}
      />
      <View style={[styles.divider, { backgroundColor: theme.divider }]} />
      <FilterRow
        filters={subFilters}
        activeId={activeSubId}
        unreadMap={subUnreadMap}
        onSelect={onSelectSub}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  panel: {
    borderRadius: Tokens.radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    paddingVertical: Tokens.spacing[3],
    paddingHorizontal: Tokens.spacing[3],
    gap: Tokens.spacing[2],
    overflow: 'visible',
  },
  chipRow: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: Tokens.spacing[2],
    paddingTop: 6,
    paddingRight: Tokens.spacing[2],
  },
  chipOuter: {
    position: 'relative',
    overflow: 'visible',
    flexShrink: 0,
  },
  chip: {
    justifyContent: 'center',
    alignSelf: 'flex-start',
    flexShrink: 0,
    minHeight: 28,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: Tokens.radius.pill,
    borderWidth: StyleSheet.hairlineWidth,
  },
  chipText: {
    fontSize: 12,
    fontWeight: '500',
    letterSpacing: 0.1,
    flexShrink: 0,
  },
  chipTextActive: {
    fontWeight: '600',
  },
  badge: {
    position: 'absolute',
    top: 0,
    right: -2,
    minWidth: 14,
    height: 14,
    borderRadius: 7,
    paddingHorizontal: 3,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1.5,
    zIndex: 1,
  },
  badgeText: {
    color: BADGE.text,
    fontSize: 9,
    fontWeight: '700',
    lineHeight: 11,
  },
  divider: {
    height: StyleSheet.hairlineWidth,
    marginVertical: 2,
  },
});
