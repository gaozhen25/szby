import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';

import { InAppModal } from '@/components/UI/InAppModal';
import { useTheme } from '@/design/theme-context';
import { Tokens } from '@/design/tokens';

export type ConfirmDialogProps = {
  visible: boolean;
  title: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  destructive?: boolean;
  loading?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
};

/** Web 端确认弹窗（原生端请用 Alert.alert 或 useConfirmDialog） */
export function ConfirmDialog({
  visible,
  title,
  message,
  confirmText = '确认',
  cancelText = '取消',
  destructive = false,
  loading = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const theme = useTheme();
  if (!visible) return null;

  const confirmBg = destructive ? theme.danger : theme.primary;

  return (
    <InAppModal visible transparent animationType="fade" onRequestClose={() => !loading && onCancel()}>
      <Pressable style={styles.mask} onPress={() => !loading && onCancel()}>
        <Pressable
          style={[styles.card, { backgroundColor: theme.surface, borderColor: theme.border }]}
          onPress={(e) => e.stopPropagation()}
        >
          <Text style={[styles.title, { color: theme.text }]}>{title}</Text>
          <Text style={[styles.message, { color: theme.textSubtle }]}>{message}</Text>
          <View style={styles.actions}>
            <Pressable
              style={[styles.btn, { backgroundColor: theme.surface2 }]}
              onPress={onCancel}
              disabled={loading}
            >
              <Text style={[styles.btnText, { color: theme.textMuted }]}>{cancelText}</Text>
            </Pressable>
            <Pressable
              style={[styles.btn, { backgroundColor: confirmBg }]}
              onPress={onConfirm}
              disabled={loading}
            >
              {loading ? (
                <ActivityIndicator size="small" color="#FFF" />
              ) : (
                <Text style={[styles.btnText, { color: '#FFF' }]}>{confirmText}</Text>
              )}
            </Pressable>
          </View>
        </Pressable>
      </Pressable>
    </InAppModal>
  );
}

const styles = StyleSheet.create({
  mask: {
    ...StyleSheet.absoluteFillObject,
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
    lineHeight: 20,
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
    alignItems: 'center',
    justifyContent: 'center',
  },
  btnText: {
    fontSize: 15,
    fontWeight: '600',
  },
});
