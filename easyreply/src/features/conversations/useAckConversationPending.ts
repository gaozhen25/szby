import { useCallback, useRef, useState } from 'react';
import { appAlert } from '@/lib/app-alert';
import type { MockConversation } from '@/mock/data';
import {
  canAckConversationPending,
  formatAckConversationPendingError,
  submitAckConversationPending,
} from '@/features/conversations/ack-conversation-pending';

/** 会话列表 / 批量场景：提交「已处理」，防重复点击 */
export function useAckConversationPending() {
  const submittingRef = useRef<Set<string>>(new Set());
  const [, setTick] = useState(0);

  const isAckSubmitting = useCallback((taskID: string) => {
    return submittingRef.current.has(taskID.trim());
  }, []);

  const ackProcessed = useCallback(async (conv: MockConversation): Promise<boolean> => {
    const taskID = (conv.id ?? '').trim();
    if (!taskID || !canAckConversationPending(conv)) return false;
    if (submittingRef.current.has(taskID)) return false;

    submittingRef.current.add(taskID);
    setTick((n) => n + 1);
    try {
      await submitAckConversationPending(taskID);
      return true;
    } catch (e) {
      appAlert('已处理失败', formatAckConversationPendingError(e));
      return false;
    } finally {
      submittingRef.current.delete(taskID);
      setTick((n) => n + 1);
    }
  }, []);

  return { ackProcessed, isAckSubmitting };
}
