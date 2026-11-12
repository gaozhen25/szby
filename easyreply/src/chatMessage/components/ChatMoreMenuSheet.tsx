import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { InAppModal } from '@/components/UI/InAppModal';
import { useTheme } from '@/design/theme-context';
import { getAgentId } from '@/core/im';
import { getRole } from '@/core/auth';
import type { TaskMode } from '@/core/im';
import { isLaborSkillGroup } from '@/chatMessage/room/chat-input-gate';
import { canShowChatAckPending } from '@/features/conversations/ack-conversation-pending';
import { SHOW_AGENT_TASK_MODE_IN_MORE_MENU, CHAT_MORE_MENU_LABELS } from '@/chatMessage/components/chat-more-menu-flags';

export type ChatMoreMenuModel = {
  isSupervisor: boolean;
  /** 主管旁观他人任务 → 可接管 */
  showSupervisorTakeover: boolean;
  /** 主管持有该任务（task.annotatorID === 当前登录人）→ 可完成 / 归还 */
  isSupervisorOwnTask: boolean;
  /** 客服本人活跃会话 → 可转派给其他客服 */
  showAgentTransfer: boolean;
  showAgentTaskMode: boolean;
  agentTaskModeLabel: string;
  /** 已处理：本人任务 + human 模式 + 有红点时才显示 */
  showAckPending: boolean;
};

export function deriveChatMoreMenuModel(opts: {
  taskAnnotatorID: string | null;
  taskMode: TaskMode | null;
  /** task.skillGroup：labor 常驻 AI 托管，不给切换入口 */
  skillGroup?: string | null;
  currentHasRedDot: boolean;
}): ChatMoreMenuModel {
  const { taskAnnotatorID, taskMode, skillGroup, currentHasRedDot } = opts;
  const isSupervisor = getRole() === 'supervisor';
  return {
    isSupervisor,
    // 主管操作菜单：task.annotatorID === 当前登录人 → 自己的任务；否则为旁观他人任务
    isSupervisorOwnTask: isSupervisor && !!taskAnnotatorID && taskAnnotatorID === getAgentId(),
    showSupervisorTakeover: isSupervisor && !!taskAnnotatorID && taskAnnotatorID !== getAgentId(),
    showAgentTransfer: !isSupervisor && !!taskAnnotatorID && taskAnnotatorID === getAgentId(),
    showAgentTaskMode:
      SHOW_AGENT_TASK_MODE_IN_MORE_MENU &&
      !isSupervisor &&
      !isLaborSkillGroup(skillGroup) &&
      (taskMode === 'human' || taskMode === 'ai_assisted'),
    agentTaskModeLabel: taskMode === 'ai_assisted' ? '关闭AI托管' : '开启AI托管',
    showAckPending: canShowChatAckPending({
      taskAnnotatorID,
      taskMode,
      currentHasRedDot,
    }),
  };
}

/** 更多操作菜单：上报 / 转移 / 结束 / 接管会话 / 还给原客服 */
export function ChatMoreMenuSheet({
  visible,
  taskAnnotatorID,
  taskMode,
  skillGroup,
  currentHasRedDot,
  ackSubmitting,
  taskModeSubmitting,
  takeoverSubmitting,
  transferSubmitting,
  returnSubmitting,
  completeSubmitting,
  onClose,
  onAckProcessed,
  onOpenReport,
  onToggleTaskMode,
  onEndChat,
  onTakeover,
  onOpenTransfer,
  onCompleteTask,
  onReturnToAgent,
}: {
  visible: boolean;
  taskAnnotatorID: string | null;
  taskMode: TaskMode | null;
  skillGroup?: string | null;
  currentHasRedDot: boolean;
  ackSubmitting: boolean;
  taskModeSubmitting: boolean;
  takeoverSubmitting: boolean;
  transferSubmitting: boolean;
  returnSubmitting: boolean;
  completeSubmitting: boolean;
  onClose: () => void;
  onAckProcessed: () => void;
  onOpenReport: () => void;
  onToggleTaskMode: () => void;
  onEndChat: () => void;
  onTakeover: () => void;
  onOpenTransfer: () => void;
  onCompleteTask: () => void;
  onReturnToAgent: () => void;
}) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const {
    isSupervisor,
    isSupervisorOwnTask,
    showSupervisorTakeover,
    showAgentTransfer,
    showAgentTaskMode,
    agentTaskModeLabel,
    showAckPending,
  } = deriveChatMoreMenuModel({ taskAnnotatorID, taskMode, skillGroup, currentHasRedDot });

  return (
    <InAppModal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={onClose}
    >
      <Pressable style={styles.sheetMask} onPress={onClose}>
        <Pressable
          style={[styles.sheetCard, { backgroundColor: theme.surface, paddingBottom: Math.max(insets.bottom, 12) }]}
          onPress={() => {}}
        >
          {/* 已处理：本人 + human + hasRedDot；暂停待处理超时倒计时（不清红点） */}
          {showAckPending ? (
            <>
              <Pressable
                style={({ pressed }) => [styles.sheetItem, pressed && { opacity: 0.7 }]}
                onPress={onAckProcessed}
                disabled={ackSubmitting}
              >
                {ackSubmitting ? (
                  <Text style={[styles.sheetItemText, { color: theme.textMuted }]}>
                    {CHAT_MORE_MENU_LABELS.ackSubmitting}
                  </Text>
                ) : (
                  <Text style={[styles.sheetItemText, { color: theme.primary }]}>{CHAT_MORE_MENU_LABELS.ack}</Text>
                )}
              </Pressable>
              <View style={[styles.sheetDivider, { backgroundColor: theme.divider }]} />
            </>
          ) : null}
          {!isSupervisor ? (
            <>
              <Pressable
                style={({ pressed }) => [styles.sheetItem, pressed && { opacity: 0.7 }]}
                onPress={onOpenReport}
              >
                <Text style={[styles.sheetItemText, { color: theme.warning }]}>{CHAT_MORE_MENU_LABELS.report}</Text>
              </Pressable>
              {showAgentTransfer ? (
                <>
                  <View style={[styles.sheetDivider, { backgroundColor: theme.divider }]} />
                  <Pressable
                    style={({ pressed }) => [styles.sheetItem, pressed && { opacity: 0.7 }]}
                    onPress={onOpenTransfer}
                    disabled={transferSubmitting}
                  >
                    {transferSubmitting ? (
                      <ActivityIndicator size="small" color={theme.primary} />
                    ) : (
                      <Text style={[styles.sheetItemText, { color: theme.text }]}>{CHAT_MORE_MENU_LABELS.transfer}</Text>
                    )}
                  </Pressable>
                </>
              ) : null}
              {showAgentTaskMode ? (
                <>
                  <View style={[styles.sheetDivider, { backgroundColor: theme.divider }]} />
                  <Pressable
                    style={({ pressed }) => [styles.sheetItem, pressed && { opacity: 0.7 }]}
                    onPress={onToggleTaskMode}
                    disabled={taskModeSubmitting}
                  >
                    {taskModeSubmitting ? (
                      <ActivityIndicator size="small" color={theme.primary} />
                    ) : (
                      <Text style={[styles.sheetItemText, { color: theme.primary }]}>{agentTaskModeLabel}</Text>
                    )}
                  </Pressable>
                </>
              ) : null}
              <View style={[styles.sheetDivider, { backgroundColor: theme.divider }]} />
              <Pressable
                style={({ pressed }) => [styles.sheetItem, pressed && { opacity: 0.7 }]}
                onPress={onEndChat}
              >
                <Text style={[styles.sheetItemText, { color: theme.danger }]}>{CHAT_MORE_MENU_LABELS.end}</Text>
              </Pressable>
            </>
          ) : (
            <>
              {showSupervisorTakeover ? (
                <Pressable
                  style={({ pressed }) => [styles.sheetItem, pressed && { opacity: 0.7 }]}
                  onPress={onTakeover}
                  disabled={takeoverSubmitting}
                >
                  {takeoverSubmitting ? (
                    <ActivityIndicator size="small" color={theme.primary} />
                  ) : (
                    <Text style={[styles.sheetItemText, { color: theme.primary }]}>{CHAT_MORE_MENU_LABELS.takeover}</Text>
                  )}
                </Pressable>
              ) : null}
              {isSupervisorOwnTask ? (
                <>
                  <Pressable
                    style={({ pressed }) => [styles.sheetItem, pressed && { opacity: 0.7 }]}
                    onPress={onCompleteTask}
                    disabled={completeSubmitting}
                  >
                    {completeSubmitting ? (
                      <ActivityIndicator size="small" color={theme.text} />
                    ) : (
                      <Text style={[styles.sheetItemText, { color: theme.text }]}>{CHAT_MORE_MENU_LABELS.complete}</Text>
                    )}
                  </Pressable>
                  <View style={[styles.sheetDivider, { backgroundColor: theme.divider }]} />
                  <Pressable
                    style={({ pressed }) => [styles.sheetItem, pressed && { opacity: 0.7 }]}
                    onPress={onReturnToAgent}
                    disabled={returnSubmitting}
                  >
                    {returnSubmitting ? (
                      <ActivityIndicator size="small" color={theme.text} />
                    ) : (
                      <Text style={[styles.sheetItemText, { color: theme.text }]}>{CHAT_MORE_MENU_LABELS.return}</Text>
                    )}
                  </Pressable>
                </>
              ) : null}
            </>
          )}
          <View style={[styles.sheetGap, { backgroundColor: theme.surface2 }]} />
          <View style={[styles.sheetDivider, { backgroundColor: theme.divider }]} />
          <Pressable
            style={({ pressed }) => [styles.sheetItem, pressed && { opacity: 0.7 }]}
            onPress={onClose}
          >
            <Text style={[styles.sheetItemText, { color: theme.textMuted }]}>{CHAT_MORE_MENU_LABELS.cancel}</Text>
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
  sheetCard: { borderTopLeftRadius: 16, borderTopRightRadius: 16, overflow: 'hidden' },
  sheetItem: { minHeight: 52, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 16 },
  sheetItemText: { fontSize: 16, fontWeight: '600' },
  sheetDivider: { height: StyleSheet.hairlineWidth },
  sheetGap: { height: 8 },
});
