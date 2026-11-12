import { useCallback, useMemo } from 'react';

import type { MockConversation } from '@/mock/data';
import { useBatchCompleteSessions } from '@/features/conversations/batch-complete';
import { useBatchTransferSessions } from '@/features/conversations/batch-transfer';

export type ConversationListBatchKind = 'complete' | 'transfer' | null;

export function useConversationListBatchActions(activeList: MockConversation[]) {
  const batchComplete = useBatchCompleteSessions(activeList);
  const batchTransfer = useBatchTransferSessions(activeList);

  const batchKind: ConversationListBatchKind = batchComplete.batchSelectMode
    ? 'complete'
    : batchTransfer.batchSelectMode
      ? 'transfer'
      : null;

  const batchSelectMode = batchKind != null;
  const batchPreparing = batchComplete.batchPreparing;
  const selectedTaskIds =
    batchKind === 'complete'
      ? batchComplete.selectedTaskIds
      : batchKind === 'transfer'
        ? batchTransfer.selectedTaskIds
        : new Set<string>();

  const cancelBatchSelect = useCallback(() => {
    batchComplete.cancelBatchSelect();
    batchTransfer.cancelBatchSelect();
  }, [batchComplete.cancelBatchSelect, batchTransfer.cancelBatchSelect]);

  const toggleBatchSelection = useCallback(
    (taskId: string) => {
      if (batchKind === 'complete') batchComplete.toggleBatchSelection(taskId);
      else if (batchKind === 'transfer') batchTransfer.toggleBatchSelection(taskId);
    },
    [batchComplete.toggleBatchSelection, batchKind, batchTransfer.toggleBatchSelection],
  );

  const startBatchComplete = useCallback(() => {
    batchTransfer.cancelBatchSelect();
    batchComplete.handleBatchActionPress();
  }, [batchComplete.handleBatchActionPress, batchTransfer.cancelBatchSelect]);

  const startBatchTransfer = useCallback(() => {
    batchComplete.cancelBatchSelect();
    batchTransfer.handleBatchActionPress();
  }, [batchComplete.cancelBatchSelect, batchTransfer.handleBatchActionPress]);

  const confirmBatchAction = useCallback(() => {
    if (batchKind === 'complete') batchComplete.handleBatchActionPress();
    else if (batchKind === 'transfer') batchTransfer.handleBatchActionPress();
  }, [batchComplete.handleBatchActionPress, batchKind, batchTransfer.handleBatchActionPress]);

  const batchActionBusy =
    batchComplete.batchCompleting || batchTransfer.transferSubmitting;

  const transferPickerProps = useMemo(
    () => ({
      visible: batchTransfer.transferPickerOpen,
      confirming: batchTransfer.transferSubmitting,
      title: '批量转移会话',
      onClose: batchTransfer.closeTransferPicker,
      onConfirm: batchTransfer.handleTransferToAgent,
    }),
    [
      batchTransfer.closeTransferPicker,
      batchTransfer.handleTransferToAgent,
      batchTransfer.transferPickerOpen,
      batchTransfer.transferSubmitting,
    ],
  );

  return {
    batchKind,
    batchSelectMode,
    batchPreparing,
    selectedTaskIds,
    batchCompleting: batchComplete.batchCompleting,
    transferSubmitting: batchTransfer.transferSubmitting,
    batchActionBusy,
    cancelBatchSelect,
    toggleBatchSelection,
    startBatchComplete,
    startBatchTransfer,
    confirmBatchAction,
    batchConfirmModalProps: batchComplete.batchConfirmModalProps,
    transferPickerProps,
  };
}
