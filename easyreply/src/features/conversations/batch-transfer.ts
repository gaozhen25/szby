import { useCallback, useState } from 'react';

import { transferTasks } from '@/api/tasks';
import { getAgentId } from '@/core/im';
import { appAlert } from '@/lib/app-alert';
import type { MockConversation } from '@/mock/data';
import {
  formatTransferError,
  isTransferAgentSelectable,
  type TransferAgent,
} from '@/features/conversations/transfer-agent';

export function useBatchTransferSessions(conversations: MockConversation[]) {
  const [batchSelectMode, setBatchSelectMode] = useState(false);
  const [selectedTaskIds, setSelectedTaskIds] = useState<Set<string>>(() => new Set());
  const [transferPickerOpen, setTransferPickerOpen] = useState(false);
  const [transferSubmitting, setTransferSubmitting] = useState(false);

  const resetBatchSelect = useCallback(() => {
    setBatchSelectMode(false);
    setSelectedTaskIds(new Set());
    setTransferPickerOpen(false);
  }, []);

  const startBatchSelect = useCallback(() => {
    const hasActive = conversations.some((c) => !c.inactive && c.id?.trim());
    if (!hasActive) {
      appAlert('提示', '当前没有可转移的活跃会话');
      return;
    }
    setBatchSelectMode(true);
    setSelectedTaskIds(new Set());
  }, [conversations]);

  const cancelBatchSelect = useCallback(() => {
    if (transferSubmitting) return;
    resetBatchSelect();
  }, [resetBatchSelect, transferSubmitting]);

  const toggleBatchSelection = useCallback((taskId: string) => {
    const id = taskId.trim();
    if (!id) return;
    setSelectedTaskIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const closeTransferPicker = useCallback(() => {
    if (transferSubmitting) return;
    setTransferPickerOpen(false);
  }, [transferSubmitting]);

  const handleBatchActionPress = useCallback(() => {
    if (transferSubmitting) return;
    if (!batchSelectMode) {
      startBatchSelect();
      return;
    }

    const taskIDs = [...selectedTaskIds].map((id) => id.trim()).filter(Boolean);
    if (!taskIDs.length) {
      appAlert('提示', '请至少选择一个会话');
      return;
    }
    setTransferPickerOpen(true);
  }, [batchSelectMode, selectedTaskIds, startBatchSelect, transferSubmitting]);

  const handleTransferToAgent = useCallback(
    (agent: TransferAgent) => {
      if (transferSubmitting) return;
      const toId = agent.agent_id.trim();
      if (!toId || toId === getAgentId() || !isTransferAgentSelectable(agent)) {
        appAlert('无法转移', '请选择已上班且未达会话上限的客服');
        return;
      }

      const taskIDs = [...selectedTaskIds].map((id) => id.trim()).filter(Boolean);
      if (!taskIDs.length) return;

      void (async () => {
        setTransferSubmitting(true);
        try {
          await transferTasks(taskIDs, toId);
          setTransferPickerOpen(false);
          resetBatchSelect();
          appAlert('已提交', `已提交转移 ${taskIDs.length} 个会话`);
        } catch (e) {
          appAlert('转移失败', formatTransferError(e));
        } finally {
          setTransferSubmitting(false);
        }
      })();
    },
    [resetBatchSelect, selectedTaskIds, transferSubmitting],
  );

  return {
    batchSelectMode,
    batchPreparing: false,
    selectedTaskIds,
    transferPickerOpen,
    transferSubmitting,
    startBatchSelect,
    cancelBatchSelect,
    toggleBatchSelection,
    handleBatchActionPress,
    closeTransferPicker,
    handleTransferToAgent,
  };
}
