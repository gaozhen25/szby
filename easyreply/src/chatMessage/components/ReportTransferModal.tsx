import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { InAppModal } from '@/components/UI/InAppModal';
import { useTheme } from '@/design/theme-context';

/** 上报问题弹窗：转交主管处理，描述可选 */
export function ReportTransferModal({
  visible,
  value,
  submitting,
  onChangeText,
  onClose,
  onSubmit,
}: {
  visible: boolean;
  value: string;
  submitting: boolean;
  onChangeText: (text: string) => void;
  onClose: () => void;
  onSubmit: () => void;
}) {
  const theme = useTheme();

  return (
    <InAppModal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable style={styles.modalMask} onPress={() => !submitting && onClose()}>
        <Pressable style={[styles.modalCard, { backgroundColor: theme.surface }]} onPress={() => {}}>
          <Text style={[styles.modalTitle, { color: theme.text }]}>上报问题</Text>
          <Text style={[styles.modalDesc, { color: theme.textSubtle }]}>转交主管处理，转交后你将无法继续发送消息</Text>
          <TextInput
            style={[styles.modalInput, { color: theme.text, backgroundColor: theme.surface2, borderColor: theme.border }]}
            value={value}
            onChangeText={onChangeText}
            placeholder="请输入需要上报的问题描述（可选）"
            placeholderTextColor={theme.placeholder}
            multiline
            maxLength={500}
          />
          <View style={styles.modalActions}>
            <Pressable
              style={[styles.modalBtn, { backgroundColor: theme.surface2 }]}
              onPress={() => !submitting && onClose()}
            >
              <Text style={[styles.modalBtnText, { color: theme.textMuted }]}>取消</Text>
            </Pressable>
            <Pressable
              style={[styles.modalBtn, { backgroundColor: theme.warning }]}
              onPress={onSubmit}
              disabled={submitting}
            >
              {submitting ? (
                <ActivityIndicator size="small" color="#FFF" />
              ) : (
                <Text style={[styles.modalBtnText, { color: '#FFF' }]}>确认上报</Text>
              )}
            </Pressable>
          </View>
        </Pressable>
      </Pressable>
    </InAppModal>
  );
}

const styles = StyleSheet.create({
  modalMask: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(0,0,0,0.4)',
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 32,
  },
  modalCard: { width: '100%', borderRadius: 16, padding: 20, gap: 12 },
  modalTitle: { fontSize: 17, fontWeight: '700' },
  modalDesc: { fontSize: 13, lineHeight: 18 },
  modalInput: { minHeight: 90, borderRadius: 10, borderWidth: StyleSheet.hairlineWidth, padding: 12, fontSize: 15, textAlignVertical: 'top' },
  modalActions: { flexDirection: 'row', gap: 12, marginTop: 4 },
  modalBtn: { flex: 1, height: 44, borderRadius: 12, justifyContent: 'center', alignItems: 'center' },
  modalBtnText: { fontSize: 15, fontWeight: '600' },
});
