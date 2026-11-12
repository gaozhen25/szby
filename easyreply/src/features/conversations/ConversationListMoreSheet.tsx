import { type ReactNode } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { InAppModal } from '@/components/UI/InAppModal';
import { useTheme } from '@/design/theme-context';
import { ExportOutlined, StarOutlined, StopOutlined } from '@/ui/antd-icons';

type ConversationListMoreSheetProps = {
  visible: boolean;
  onClose: () => void;
  onBatchComplete: () => void;
  onBatchTransfer: () => void;
  onFavorites: () => void;
};

type SheetItemProps = {
  label: string;
  color: string;
  icon: ReactNode;
  onPress: () => void;
};

function SheetItem({ label, color, icon, onPress }: SheetItemProps) {
  return (
    <Pressable
      style={({ pressed }) => [styles.sheetItem, pressed && { opacity: 0.7 }]}
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={label}
    >
      <View style={styles.sheetItemInner}>
        {icon}
        <Text style={[styles.sheetItemText, { color }]}>{label}</Text>
      </View>
    </Pressable>
  );
}

/** 会话列表右上角「更多操作」底部菜单 */
export function ConversationListMoreSheet({
  visible,
  onClose,
  onBatchComplete,
  onBatchTransfer,
  onFavorites,
}: ConversationListMoreSheetProps) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();

  const run = (action: () => void) => {
    onClose();
    queueMicrotask(action);
  };

  return (
    <InAppModal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable style={styles.sheetMask} onPress={onClose}>
        <Pressable
          style={[
            styles.sheetCard,
            { backgroundColor: theme.surface, paddingBottom: Math.max(insets.bottom, 12) },
          ]}
          onPress={() => {}}
        >
          <View style={styles.sheetHeader}>
            <Text style={[styles.sheetTitle, { color: theme.textMuted }]}>更多操作</Text>
          </View>
          <View style={[styles.sheetDivider, { backgroundColor: theme.divider }]} />

          <SheetItem
            label="批量结束"
            color={theme.danger}
            icon={<StopOutlined size={20} color={theme.danger} />}
            onPress={() => run(onBatchComplete)}
          />
          <View style={[styles.sheetDivider, { backgroundColor: theme.divider }]} />
          <SheetItem
            label="批量转移"
            color={theme.text}
            icon={<ExportOutlined size={20} color={theme.text} />}
            onPress={() => run(onBatchTransfer)}
          />
          <View style={[styles.sheetDivider, { backgroundColor: theme.divider }]} />
          <SheetItem
            label="我的收藏"
            color={theme.text}
            icon={<StarOutlined size={20} color={theme.text} />}
            onPress={() => run(onFavorites)}
          />

          <View style={[styles.sheetGap, { backgroundColor: theme.surface2 }]} />
          <View style={[styles.sheetDivider, { backgroundColor: theme.divider }]} />
          <Pressable
            style={({ pressed }) => [styles.sheetItem, pressed && { opacity: 0.7 }]}
            onPress={onClose}
            accessibilityRole="button"
            accessibilityLabel="取消"
          >
            <Text style={[styles.sheetItemText, { color: theme.textMuted }]}>取消</Text>
          </Pressable>
        </Pressable>
      </Pressable>
    </InAppModal>
  );
}

const styles = StyleSheet.create({
  sheetMask: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(0,0,0,0.4)',
    justifyContent: 'flex-end',
  },
  sheetCard: {
    borderTopLeftRadius: 16,
    borderTopRightRadius: 16,
    overflow: 'hidden',
  },
  sheetHeader: {
    minHeight: 44,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 16,
  },
  sheetTitle: {
    fontSize: 13,
  },
  sheetItem: {
    minHeight: 52,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 20,
  },
  sheetItemInner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  sheetItemText: {
    fontSize: 16,
  },
  sheetDivider: {
    height: StyleSheet.hairlineWidth,
  },
  sheetGap: {
    height: 8,
  },
});
