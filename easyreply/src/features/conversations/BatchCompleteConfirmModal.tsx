import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';

import { InAppModal } from '@/components/UI/InAppModal';
import { useTheme } from '@/design/theme-context';
import { Tokens } from '@/design/tokens';
import { formatBatchCompleteMessage, type BatchCompleteConfirmModalProps } from '@/features/conversations/batch-complete';

export function BatchCompleteConfirmModal({
  visible,
  total,
  done,
  completing,
  onCancel,
  onConfirm,
}: BatchCompleteConfirmModalProps) {
  const theme = useTheme();

  return (
    <InAppModal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={completing ? undefined : onCancel}
    >
      <Pressable style={styles.backdrop} onPress={completing ? undefined : onCancel}>
        <Pressable
          style={[styles.card, { backgroundColor: theme.surface, borderColor: theme.border }]}
          onPress={(e) => e.stopPropagation()}
        >
          <Text style={[styles.title, { color: theme.text }]}>批量结束</Text>
          <Text style={[styles.message, { color: theme.textSubtle }]}>
            {formatBatchCompleteMessage(total, done, completing)}
          </Text>
          <View style={styles.actions}>
            <Pressable
              onPress={onCancel}
              disabled={completing}
              style={[
                styles.btn,
                { borderColor: theme.border, backgroundColor: theme.surface2 },
                completing && styles.btnDisabled,
              ]}
            >
              <Text style={{ color: theme.textMuted }}>取消</Text>
            </Pressable>
            <Pressable
              onPress={onConfirm}
              disabled={completing}
              style={[
                styles.btn,
                styles.btnPrimary,
                { backgroundColor: theme.danger },
                completing && styles.btnDisabled,
              ]}
            >
              {completing ? (
                <ActivityIndicator size="small" color="#FFFFFF" />
              ) : (
                <Text style={styles.btnPrimaryText}>确定结束</Text>
              )}
            </Pressable>
          </View>
        </Pressable>
      </Pressable>
    </InAppModal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.4)',
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: Tokens.spacing[8],
  },
  card: {
    width: '100%',
    maxWidth: 400,
    borderRadius: Tokens.radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    padding: Tokens.spacing[5],
    gap: Tokens.spacing[3],
  },
  title: {
    fontSize: 17,
    fontWeight: '700',
  },
  message: {
    fontSize: 14,
    lineHeight: 22,
  },
  actions: {
    flexDirection: 'row',
    gap: Tokens.spacing[3],
    marginTop: Tokens.spacing[1],
  },
  btn: {
    flex: 1,
    height: 44,
    borderRadius: Tokens.radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    alignItems: 'center',
    justifyContent: 'center',
  },
  btnPrimary: {
    borderWidth: 0,
  },
  btnPrimaryText: {
    color: '#FFFFFF',
    fontSize: 15,
    fontWeight: '600',
  },
  btnDisabled: {
    opacity: 0.65,
  },
});
