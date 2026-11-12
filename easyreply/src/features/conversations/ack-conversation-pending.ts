import { ackTaskPending } from '@/api/tasks';
import { getRole } from '@/core/auth';
import { getAgentId } from '@/core/im';
import type { TaskMode } from '@/core/im';
import type { MockConversation } from '@/mock/data';

/** 聊天页「更多」菜单：本人任务 + human + 红点 */
export function canShowChatAckPending(opts: {
  taskAnnotatorID: string | null;
  taskMode: TaskMode | null;
  currentHasRedDot: boolean;
}): boolean {
  const { taskAnnotatorID, taskMode, currentHasRedDot } = opts;
  if (getRole() === 'supervisor') return false;
  return (
    !!taskAnnotatorID &&
    taskAnnotatorID === getAgentId() &&
    taskMode === 'human' &&
    currentHasRedDot
  );
}

/** 会话列表左滑/右键：活跃 + human + 红点 */
export function canAckConversationPending(
  conv: Pick<MockConversation, 'inactive' | 'hasRedDot' | 'taskMode'>,
): boolean {
  if (getRole() === 'supervisor') return false;
  if (conv.inactive) return false;
  if (!conv.hasRedDot) return false;
  return conv.taskMode === 'human';
}

export async function submitAckConversationPending(taskID: string): Promise<void> {
  const id = taskID.trim();
  if (!id) throw new Error('缺少任务 ID');
  await ackTaskPending(id);
}

export function formatAckConversationPendingError(e: unknown, fallback = '请稍后重试'): string {
  return e instanceof Error ? e.message : fallback;
}
