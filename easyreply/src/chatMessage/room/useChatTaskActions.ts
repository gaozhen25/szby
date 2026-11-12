import { useCallback, useState, type Dispatch, type SetStateAction } from 'react';
import { appAlert } from '@/lib/app-alert';
import {
  completeTask,
  reportTransfer,
  setTaskMode,
  supervisorReturnToAgent,
  supervisorTakeover,
  transferTask,
} from '@/api/tasks';
import { getAgentId, type TaskMode } from '@/core/im';
import {
  formatAckConversationPendingError,
  submitAckConversationPending,
} from '@/features/conversations/ack-conversation-pending';
import {
  gateAfterTaskMode,
  isLaborSkillGroup,
  type ChatInputGate,
} from '@/chatMessage/room/chat-input-gate';
import { updateConversationTaskMode } from '@/lib/claimed-conversations-store';
import { formatTransferError, isTransferAgentSelectable, type TransferAgent } from '@/features/conversations/transfer-agent';

/**
 * 聊天页「...」菜单里的任务动作：上报 / 转移 / 结束 / AI托管 / 接管 / 归还 / 标记完成 / 已处理。
 * 每个动作都是「二次确认 → 调接口 → 置 submitting → 更新门禁」。
 */
export function useChatTaskActions(opts: {
  taskID: string;
  taskMode: TaskMode | null;
  /** task.skillGroup：labor 等同 AI 托管且不可切换 */
  skillGroup: string | null;
  setInputGate: Dispatch<SetStateAction<ChatInputGate>>;
  setTaskModeState: Dispatch<SetStateAction<TaskMode | null>>;
  closeMoreMenu: () => void;
}) {
  const { taskID, taskMode, skillGroup, setInputGate, setTaskModeState, closeMoreMenu } = opts;
  const laborSkillGroup = isLaborSkillGroup(skillGroup);

  const [reportOpen, setReportOpen] = useState(false);
  const [reportText, setReportText] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [takeoverSubmitting, setTakeoverSubmitting] = useState(false);
  const [transferPickerOpen, setTransferPickerOpen] = useState(false);
  const [transferSubmitting, setTransferSubmitting] = useState(false);
  const [returnSubmitting, setReturnSubmitting] = useState(false);
  const [completeSubmitting, setCompleteSubmitting] = useState(false);
  const [ackSubmitting, setAckSubmitting] = useState(false);
  const [taskModeSubmitting, setTaskModeSubmitting] = useState(false);

  const handleReportSubmit = useCallback(async () => {
    if (submitting) return;
    setSubmitting(true);
    try {
      const reason = reportText.trim();
      await reportTransfer(taskID, { reason: reason || undefined });
      setReportOpen(false);
      setReportText('');
      appAlert('提示', '已上报，等待主管处理');
    } catch (e) {
      appAlert('上报失败', e instanceof Error ? e.message : '请稍后重试');
    } finally {
      setSubmitting(false);
    }
  }, [submitting, taskID, reportText]);

  const handleEndChat = useCallback(() => {
    if (completeSubmitting) return;
    closeMoreMenu();
    appAlert('结束会话', '确认结束当前会话？', [
      { text: '取消', style: 'cancel' },
      {
        text: '结束',
        style: 'destructive',
        onPress: () => {
          void (async () => {
            setCompleteSubmitting(true);
            try {
              await completeTask(taskID, 'resolved');
              setInputGate({ phase: 'locked', reason: '已提交结束，等待结果…' });
            } catch (e) {
              appAlert('结束失败', e instanceof Error ? e.message : '请稍后重试');
            } finally {
              setCompleteSubmitting(false);
            }
          })();
        },
      },
    ]);
  }, [completeSubmitting, taskID, closeMoreMenu, setInputGate]);

  const handleToggleTaskMode = useCallback(() => {
    if (taskModeSubmitting || !taskMode || laborSkillGroup) return;
    const nextMode: TaskMode = taskMode === 'human' ? 'ai_assisted' : 'human';
    const title = taskMode === 'human' ? '开启AI托管' : '关闭AI托管';
    const message = taskMode === 'human'
      ? '确认开启 AI 托管？开启后将由 AI 协助处理该会话。'
      : '确认关闭 AI 托管？关闭后将恢复人工处理。';

    closeMoreMenu();

    const run = async () => {
      setTaskModeSubmitting(true);
      try {
        await setTaskMode(taskID, nextMode);
        setTaskModeState(nextMode);
        setInputGate((g) => gateAfterTaskMode(g, { taskMode: nextMode, skillGroup }));
        // 本地会话缓存同步写入（AI 托管存 ai_assisted，勿存 ai）
        updateConversationTaskMode({ taskID, taskMode: nextMode });
      } catch (e) {
        appAlert('操作失败', e instanceof Error ? e.message : '请稍后重试');
      } finally {
        setTaskModeSubmitting(false);
      }
    };

    appAlert(title, message, [
      { text: '取消', style: 'cancel' },
      { text: '确认', onPress: () => { void run(); } },
    ]);
  }, [
    taskMode,
    taskModeSubmitting,
    laborSkillGroup,
    skillGroup,
    taskID,
    closeMoreMenu,
    setInputGate,
    setTaskModeState,
  ]);

  const handleTakeover = useCallback(() => {
    if (takeoverSubmitting) return;
    closeMoreMenu();

    const run = async () => {
      setTakeoverSubmitting(true);
      try {
        await supervisorTakeover(taskID);
      } catch (e) {
        appAlert('接管失败', e instanceof Error ? e.message : '请稍后重试');
      } finally {
        setTakeoverSubmitting(false);
      }
    };

    appAlert('接管会话', '确认接管当前会话？接管后你将成为该任务的处理人。', [
      { text: '取消', style: 'cancel' },
      { text: '确认接管', onPress: () => { void run(); } },
    ]);
  }, [takeoverSubmitting, taskID, closeMoreMenu]);

  const handleOpenTransfer = useCallback(() => {
    if (transferSubmitting) return;
    closeMoreMenu();
    setTransferPickerOpen(true);
  }, [transferSubmitting, closeMoreMenu]);

  const closeTransferPicker = useCallback(() => {
    if (transferSubmitting) return;
    setTransferPickerOpen(false);
  }, [transferSubmitting]);

  const handleTransferToAgent = useCallback(
    (agent: TransferAgent) => {
      if (transferSubmitting) return;
      const toId = agent.agent_id.trim();
      if (!toId || toId === getAgentId() || !isTransferAgentSelectable(agent)) {
        appAlert('无法转移', '请选择已上班且未达会话上限的客服');
        return;
      }

      void (async () => {
        setTransferSubmitting(true);
        try {
          await transferTask(taskID, toId);
          setTransferPickerOpen(false);
          setInputGate({ phase: 'locked', reason: '已提交转移，等待结果…' });
        } catch (e) {
          appAlert('转移失败', formatTransferError(e));
        } finally {
          setTransferSubmitting(false);
        }
      })();
    },
    [transferSubmitting, taskID, setInputGate],
  );

  const handleReturnToAgent = useCallback(() => {
    if (returnSubmitting) return;
    closeMoreMenu();

    const run = async () => {
      setReturnSubmitting(true);
      try {
        await supervisorReturnToAgent(taskID);
        setInputGate({ phase: 'locked', reason: '已发起归还，等待结果…' });
      } catch (e) {
        appAlert('归还失败', e instanceof Error ? e.message : '请稍后重试');
      } finally {
        setReturnSubmitting(false);
      }
    };

    appAlert('还给原客服', '确认将当前会话还给原客服？', [
      { text: '取消', style: 'cancel' },
      { text: '确认归还', onPress: () => { void run(); } },
    ]);
  }, [returnSubmitting, taskID, closeMoreMenu, setInputGate]);

  const handleCompleteTask = useCallback(() => {
    if (completeSubmitting) return;
    closeMoreMenu();

    const run = async () => {
      setCompleteSubmitting(true);
      try {
        // 暂使用固定 reason；如需可扩展为弹窗输入
        await completeTask(taskID, 'resolved');
        setInputGate({ phase: 'locked', reason: '已提交“标记任务完成”，等待结果…' });
      } catch (e) {
        appAlert('标记完成失败', e instanceof Error ? e.message : '请稍后重试');
      } finally {
        setCompleteSubmitting(false);
      }
    };

    appAlert('标记任务完成', '确认标记该任务完成？完成后该任务将被显式关闭。', [
      { text: '取消', style: 'cancel' },
      { text: '确认', onPress: () => { void run(); } },
    ]);
  }, [completeSubmitting, taskID, closeMoreMenu, setInputGate]);

  const handleOpenReport = useCallback(() => {
    closeMoreMenu();
    // labor 不提供托管开关，拦下来会无路可走
    if (taskMode === 'ai_assisted' && !laborSkillGroup) {
      appAlert('无法上报', '请先关闭AI托管');
      return;
    }
    setReportOpen(true);
  }, [taskMode, laborSkillGroup, closeMoreMenu]);

  /** 已处理：暂停待处理超时倒计时；红点待 WS ack_pending_result ok 后清除 */
  const handleAckProcessed = useCallback(() => {
    if (ackSubmitting) return;
    closeMoreMenu();

    void (async () => {
      setAckSubmitting(true);
      try {
        await submitAckConversationPending(taskID);
        // 最终以 WS ack_pending_result 为准；此处仅入队
      } catch (e) {
        appAlert('操作失败', formatAckConversationPendingError(e));
      } finally {
        setAckSubmitting(false);
      }
    })();
  }, [ackSubmitting, taskID, closeMoreMenu]);

  const closeReport = useCallback(() => setReportOpen(false), []);

  return {
    reportOpen,
    reportText,
    setReportText,
    closeReport,
    submitting,
    takeoverSubmitting,
    transferPickerOpen,
    transferSubmitting,
    returnSubmitting,
    completeSubmitting,
    ackSubmitting,
    taskModeSubmitting,
    handleReportSubmit,
    handleEndChat,
    handleToggleTaskMode,
    handleTakeover,
    handleOpenTransfer,
    closeTransferPicker,
    handleTransferToAgent,
    handleReturnToAgent,
    handleCompleteTask,
    handleOpenReport,
    handleAckProcessed,
  };
}
