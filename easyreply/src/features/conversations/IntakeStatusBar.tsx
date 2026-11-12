import { useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { InAppModal } from '@/components/UI/InAppModal';
import { useTheme } from '@/design/theme-context';
import { Tokens } from '@/design/tokens';
import { PauseOutlined, PlayCircleFilled } from '@/ui/antd-icons';

import type { useIntakeControls } from '@/features/conversations/useIntakeControls';

type IntakeControls = ReturnType<typeof useIntakeControls>;

export function IntakeStatusBar({
  isSupervisor,
  intakePaused,
  intakeReason,
  intakeLoading,
  intakeToggling,
  handleToggleIntake,
}: Pick<
  IntakeControls,
  | 'isSupervisor'
  | 'intakePaused'
  | 'intakeReason'
  | 'intakeLoading'
  | 'intakeToggling'
  | 'handleToggleIntake'
>) {
  const theme = useTheme();
  const [reasonModalVisible, setReasonModalVisible] = useState(false);

  if (isSupervisor) return null;

  const receiving = !intakePaused;
  const busy = intakeLoading || intakeToggling;

  return (
    <View
      style={[
        styles.bar,
        {
          backgroundColor: receiving ? theme.successSoft : theme.surface2,
          borderColor: receiving ? theme.success + '33' : theme.border,
        },
      ]}
    >
      <View style={styles.copy}>
        <Text
          style={[
            styles.title,
            { color: receiving ? theme.primary : theme.danger },
          ]}
        >
          {receiving ? '接待新任务' : '已停止接待任务'}
        </Text>
        {intakePaused && intakeReason ? (
          <Pressable
            onPress={() => setReasonModalVisible(true)}
            accessibilityRole="button"
            accessibilityLabel="查看暂停原因"
            style={({ pressed }) => [pressed && { opacity: 0.75 }]}
          >
            <Text style={[styles.reason, { color: theme.textMuted }]} numberOfLines={1}>
              {intakeReason}
            </Text>
          </Pressable>
        ) : receiving ? (
          <Text style={[styles.reason, { color: theme.textMuted }]} numberOfLines={1}>
            系统会继续分配新会话
          </Text>
        ) : null}
      </View>
      <Pressable
        onPress={handleToggleIntake}
        disabled={busy}
        style={({ pressed }) => [
          styles.toggle,
          {
            backgroundColor: receiving ? theme.successSoft : theme.surface,
            borderColor: receiving ? theme.success + '55' : theme.border,
            opacity: busy ? 0.55 : pressed ? 0.88 : 1,
          },
        ]}
        accessibilityRole="switch"
        accessibilityState={{ checked: receiving, disabled: busy }}
        accessibilityLabel={receiving ? '正在接待新任务，点击暂停' : '已暂停接待新任务，点击恢复'}
      >
        {receiving ? (
          <PlayCircleFilled size={13} color={theme.success} />
        ) : (
          <PauseOutlined size={13} color={theme.warning} />
        )}
        <Text style={[styles.toggleText, { color: theme.text }]}>
          {receiving ? '开启' : '暂停'}
        </Text>
      </Pressable>
      <IntakeReasonModal
        visible={reasonModalVisible}
        reason={intakeReason}
        onClose={() => setReasonModalVisible(false)}
      />
    </View>
  );
}

export function IntakeReasonModal({
  visible,
  reason,
  onClose,
}: {
  visible: boolean;
  reason: string;
  onClose: () => void;
}) {
  const theme = useTheme();

  if (!reason.trim()) return null;

  return (
    <InAppModal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable style={styles.modalBackdrop} onPress={onClose}>
        <Pressable
          style={[styles.modalCard, { backgroundColor: theme.surface, borderColor: theme.border }]}
          onPress={(e) => e.stopPropagation()}
        >
          <Text style={[styles.modalTitle, { color: theme.text }]}>暂停原因</Text>
          <Text style={[styles.reasonBody, { color: theme.text }]}>{reason}</Text>
          <View style={styles.modalActions}>
            <Pressable
              onPress={onClose}
              style={[
                styles.modalBtn,
                styles.modalBtnPrimary,
                { backgroundColor: theme.primary, flex: 1 },
              ]}
            >
              <Text style={{ color: '#FFFFFF', textAlign: 'center' }}>知道了</Text>
            </Pressable>
          </View>
        </Pressable>
      </Pressable>
    </InAppModal>
  );
}

export function IntakePauseModal({
  pauseModalVisible,
  pauseReasonDraft,
  setPauseReasonDraft,
  confirmPauseIntake,
  cancelPauseIntake,
  intakeToggling,
}: Pick<
  IntakeControls,
  | 'pauseModalVisible'
  | 'pauseReasonDraft'
  | 'setPauseReasonDraft'
  | 'confirmPauseIntake'
  | 'cancelPauseIntake'
  | 'intakeToggling'
>) {
  const theme = useTheme();

  return (
    <InAppModal visible={pauseModalVisible} transparent animationType="fade" onRequestClose={cancelPauseIntake}>
      <Pressable style={styles.modalBackdrop} onPress={cancelPauseIntake}>
        <Pressable
          style={[styles.modalCard, { backgroundColor: theme.surface, borderColor: theme.border }]}
          onPress={(e) => e.stopPropagation()}
        >
          <Text style={[styles.modalTitle, { color: theme.text }]}>暂停接待新任务</Text>
          <Text style={[styles.modalHint, { color: theme.textMuted }]}>
            暂停后不会再分配新任务，已有会话不受影响，也不会改变上班/下班状态。
          </Text>
          <TextInput
            style={[
              styles.modalInput,
              { color: theme.text, borderColor: theme.border, backgroundColor: theme.surface2 },
            ]}
            placeholder="暂停原因（选填）"
            placeholderTextColor={theme.placeholder}
            value={pauseReasonDraft}
            onChangeText={setPauseReasonDraft}
            multiline
            maxLength={200}
          />
          <View style={styles.modalActions}>
            <Pressable
              onPress={cancelPauseIntake}
              style={[styles.modalBtn, { borderColor: theme.border }]}
            >
              <Text style={{ color: theme.text }}>取消</Text>
            </Pressable>
            <Pressable
              onPress={confirmPauseIntake}
              disabled={intakeToggling}
              style={[
                styles.modalBtn,
                styles.modalBtnPrimary,
                { backgroundColor: theme.primary, opacity: intakeToggling ? 0.6 : 1 },
              ]}
            >
              <Text style={{ color: '#FFFFFF' }}>确认暂停</Text>
            </Pressable>
          </View>
        </Pressable>
      </Pressable>
    </InAppModal>
  );
}

const styles = StyleSheet.create({
  bar: {
    marginBottom: Tokens.spacing[1],
    paddingHorizontal: Tokens.spacing[2],
    paddingVertical: Tokens.spacing[2],
    borderRadius: Tokens.radius.sm,
    borderWidth: StyleSheet.hairlineWidth,
    flexDirection: 'row',
    alignItems: 'center',
    gap: Tokens.spacing[2],
  },
  copy: {
    flex: 1,
    minWidth: 0,
    gap: 1,
  },
  title: {
    fontSize: 13,
    fontWeight: '600',
    lineHeight: 18,
  },
  reason: {
    fontSize: 11,
    lineHeight: 14,
  },
  toggle: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: Tokens.radius.pill,
    borderWidth: StyleSheet.hairlineWidth,
  },
  toggleText: {
    fontSize: 12,
    fontWeight: '600',
  },
  modalBackdrop: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.45)',
    alignItems: 'center',
    justifyContent: 'center',
    padding: Tokens.spacing[5],
  },
  modalCard: {
    width: '100%',
    maxWidth: 360,
    borderRadius: Tokens.radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    padding: Tokens.spacing[4],
    gap: Tokens.spacing[3],
  },
  modalTitle: {
    fontSize: 17,
    fontWeight: '400',
  },
  modalHint: {
    fontSize: 13,
    lineHeight: 18,
  },
  reasonBody: {
    fontSize: 14,
    lineHeight: 20,
  },
  modalInput: {
    minHeight: 88,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: Tokens.radius.md,
    paddingHorizontal: Tokens.spacing[3],
    paddingVertical: Tokens.spacing[3],
    textAlignVertical: 'top',
    fontSize: 14,
  },
  modalActions: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    gap: Tokens.spacing[2],
  },
  modalBtn: {
    minWidth: 88,
    paddingHorizontal: Tokens.spacing[3],
    paddingVertical: Tokens.spacing[2],
    borderRadius: Tokens.radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    alignItems: 'center',
  },
  modalBtnPrimary: {
    borderWidth: 0,
  },
});
