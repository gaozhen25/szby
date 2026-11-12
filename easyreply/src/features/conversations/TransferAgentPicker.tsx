import { useCallback } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { InAppModal } from '@/components/UI/InAppModal';
import { useTheme } from '@/design/theme-context';
import { SearchOutlined } from '@/ui/antd-icons';
import { useTransferAgentPicker } from '@/features/conversations/useTransferAgentPicker';
import {
  formatTransferAgentLoad,
  isTransferAgentSelectable,
  isTransferAgentSelf,
  transferAgentDutyStatus,
  transferAgentStatusLabel,
  type TransferAgentPickerProps,
} from '@/features/conversations/transfer-agent';

function statusColor(status: ReturnType<typeof transferAgentDutyStatus>, theme: ReturnType<typeof useTheme>) {
  return status === 'on_duty' ? theme.success : theme.textMuted;
}

export function TransferAgentPicker({
  visible,
  currentAgentId,
  confirming = false,
  title = '转移会话',
  onClose,
  onConfirm,
}: TransferAgentPickerProps) {
  const theme = useTheme();
  const picker = useTransferAgentPicker({ visible, currentAgentId });

  const handleConfirm = useCallback(() => {
    if (
      !picker.selected ||
      confirming ||
      !isTransferAgentSelectable(picker.selected, picker.currentAgentId)
    ) {
      return;
    }
    onConfirm(picker.selected);
  }, [picker.selected, picker.currentAgentId, confirming, onConfirm]);

  const canConfirm =
    !!picker.selected &&
    isTransferAgentSelectable(picker.selected, picker.currentAgentId) &&
    !confirming;

  return (
    <InAppModal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <View style={styles.mask}>
        <View style={[styles.card, { backgroundColor: theme.surface }]}>
          <Text style={[styles.title, { color: theme.text }]}>{title}</Text>
          <Text style={[styles.desc, { color: theme.textSubtle }]}>选择要转给的客服</Text>
          <View style={[styles.search, { backgroundColor: theme.surface2, borderColor: theme.border }]}>
            <SearchOutlined size={16} color={theme.placeholder} />
            <TextInput
              style={[styles.searchInput, { color: theme.text }]}
              value={picker.keyword}
              onChangeText={picker.setKeyword}
              placeholder="搜索账号"
              placeholderTextColor={theme.placeholder}
              editable={!confirming}
            />
          </View>
          <View style={styles.listWrap}>
            {picker.loading ? (
              <View style={styles.center}>
                <ActivityIndicator size="small" color={theme.primary} />
              </View>
            ) : picker.error ? (
              <Pressable style={styles.center} onPress={() => void picker.reload()}>
                <Text style={[styles.empty, { color: theme.danger }]}>{picker.error}</Text>
                <Text style={[styles.retry, { color: theme.primary }]}>点击重试</Text>
              </Pressable>
            ) : picker.filtered.length === 0 ? (
              <View style={styles.center}>
                <Text style={[styles.empty, { color: theme.textMuted }]}>暂无可转派客服</Text>
              </View>
            ) : (
              <FlatList
                data={picker.filtered}
                keyExtractor={(item) => item.agent_id}
                keyboardShouldPersistTaps="handled"
                renderItem={({ item }) => {
                  const status = transferAgentDutyStatus(item);
                  const isSelf = isTransferAgentSelf(item, picker.currentAgentId);
                  const selectable = isTransferAgentSelectable(item, picker.currentAgentId);
                  const selected = picker.selectedId === item.agent_id;
                  const color = statusColor(status, theme);
                  const muted = !selectable;
                  return (
                    <Pressable
                      onPress={() => {
                        if (!selectable) return;
                        picker.setSelectedId(item.agent_id);
                      }}
                      disabled={confirming || !selectable}
                      style={({ pressed }) => [
                        styles.row,
                        selected && selectable && { backgroundColor: theme.primarySoft },
                        muted && { opacity: 0.45 },
                        pressed && selectable && { opacity: 0.8 },
                      ]}
                    >
                      <View style={[styles.radio, { borderColor: selected && selectable ? theme.primary : theme.border }]}>
                        {selected && selectable ? <View style={[styles.radioDot, { backgroundColor: theme.primary }]} /> : null}
                      </View>
                      <View style={styles.rowBody}>
                        <View style={styles.rowTop}>
                          <View style={styles.nameRow}>
                            <Text style={[styles.name, { color: theme.text }]} numberOfLines={1}>
                              {item.agent_account || item.agent_id}
                            </Text>
                            {isSelf ? (
                              <View style={[styles.meTag, { backgroundColor: theme.primarySoft }]}>
                                <Text style={[styles.meTagText, { color: theme.primary }]}>我</Text>
                              </View>
                            ) : null}
                          </View>
                          <View style={[styles.badge, { backgroundColor: `${color}18` }]}>
                            <View style={[styles.badgeDot, { backgroundColor: color }]} />
                            <Text style={[styles.badgeText, { color }]}>
                              {transferAgentStatusLabel(status)}
                            </Text>
                          </View>
                        </View>
                        <Text style={[styles.meta, { color: theme.textMuted }]}>
                          会话 {formatTransferAgentLoad(item)}
                        </Text>
                      </View>
                    </Pressable>
                  );
                }}
              />
            )}
          </View>
          <View style={styles.actions}>
            <Pressable
              style={[styles.btn, { backgroundColor: theme.surface2 }]}
              onPress={() => !confirming && onClose()}
            >
              <Text style={[styles.btnText, { color: theme.textMuted }]}>取消</Text>
            </Pressable>
            <Pressable
              style={[
                styles.btn,
                { backgroundColor: theme.primary },
                !canConfirm && { opacity: 0.5 },
              ]}
              onPress={handleConfirm}
              disabled={!canConfirm}
            >
              {confirming ? (
                <ActivityIndicator size="small" color="#FFF" />
              ) : (
                <Text style={[styles.btnText, { color: '#FFF' }]}>确认转移</Text>
              )}
            </Pressable>
          </View>
        </View>
      </View>
    </InAppModal>
  );
}

const styles = StyleSheet.create({
  mask: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(0,0,0,0.4)',
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 24,
  },
  card: {
    width: '100%',
    maxHeight: '80%',
    borderRadius: 16,
    padding: 20,
    gap: 12,
  },
  title: { fontSize: 17, fontWeight: '700' },
  desc: { fontSize: 13, lineHeight: 18 },
  search: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    height: 40,
    borderRadius: 10,
    borderWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: 12,
  },
  searchInput: { flex: 1, fontSize: 15, padding: 0 },
  listWrap: { height: 280 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 8 },
  empty: { fontSize: 14 },
  retry: { fontSize: 13, fontWeight: '600' },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingVertical: 10,
    paddingHorizontal: 8,
    borderRadius: 10,
  },
  radio: {
    width: 18,
    height: 18,
    borderRadius: 9,
    borderWidth: 1.5,
    alignItems: 'center',
    justifyContent: 'center',
  },
  radioDot: { width: 8, height: 8, borderRadius: 4 },
  rowBody: { flex: 1, minWidth: 0, gap: 4 },
  rowTop: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  nameRow: { flex: 1, minWidth: 0, flexDirection: 'row', alignItems: 'center', gap: 6 },
  name: { flexShrink: 1, fontSize: 15, fontWeight: '600' },
  meTag: {
    flexShrink: 0,
    paddingHorizontal: 6,
    paddingVertical: 1,
    borderRadius: 4,
  },
  meTagText: { fontSize: 11, fontWeight: '600' },
  badge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 999,
  },
  badgeDot: { width: 6, height: 6, borderRadius: 3 },
  badgeText: { fontSize: 11, fontWeight: '600' },
  meta: { fontSize: 12 },
  actions: { flexDirection: 'row', gap: 12, marginTop: 4 },
  btn: {
    flex: 1,
    height: 44,
    borderRadius: 12,
    justifyContent: 'center',
    alignItems: 'center',
  },
  btnText: { fontSize: 15, fontWeight: '600' },
});
