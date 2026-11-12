import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { InteractionManager } from 'react-native';

import { completeTask } from '@/api/tasks';
import { normalizeSendTimeMs } from '@/core/im';
import { appAlert } from '@/lib/app-alert';
import { refreshClaimedConversations } from '@/lib/claimed-conversations-store';
import type { MockConversation } from '@/mock/data';

/** 批量结束全部提交完成后，延时刷新 claimed/list */
const BATCH_COMPLETE_REFRESH_DELAY_MS = 3000;
/** 默认选中计算每批处理条数，批间让出主线程 */
const BATCH_SELECTION_CHUNK_SIZE = 64;

function yieldToMainThread(): Promise<void> {
  return new Promise((resolve) => {
    if (typeof requestAnimationFrame === 'function') {
      requestAnimationFrame(() => resolve());
      return;
    }
    setTimeout(resolve, 0);
  });
}

function afterInteractions(): Promise<void> {
  return new Promise((resolve) => {
    InteractionManager.runAfterInteractions(() => resolve());
  });
}

export type BatchCompleteConfirmModalProps = {
  visible: boolean;
  total: number;
  done: number;
  completing: boolean;
  onCancel: () => void;
  onConfirm: () => void;
};

export function formatBatchCompleteMessage(total: number, done: number, completing: boolean): string {
  if (!completing) {
    return `确认结束已选的 ${total} 个活跃会话？`;
  }
  const remaining = Math.max(0, total - done);
  return `正在结束会话…\n已完成 ${done} 个，剩余 ${remaining} 个`;
}

function startOfLocalDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

/** 与列表 `time` 字段同一套自然日计算（见 formatTaskTriggerTime） */
export function getConversationListDayDiff(
  conv: MockConversation,
  now = new Date(),
): number | null {
  const ts = conv.lastMessage?.sendTime;
  if (ts == null || ts === 0 || !Number.isFinite(ts)) return null;
  const d = new Date(normalizeSendTimeMs(ts));
  if (Number.isNaN(d.getTime())) return null;
  const dayMs = 24 * 60 * 60 * 1000;
  return Math.floor((startOfLocalDay(now) - startOfLocalDay(d)) / dayMs);
}

/** 列表显示为「三天前」及更早（diffDays >= 3，见 formatTaskTriggerTime） */
export function isConversationOlderThanThreeDays(
  conv: MockConversation,
  now = new Date(),
): boolean {
  const diff = getConversationListDayDiff(conv, now);
  return diff != null && diff >= 3;
}

export function buildDefaultBatchCompleteSelection(
  conversations: MockConversation[],
  now = new Date(),
): Set<string> {
  const ids = new Set<string>();
  for (const c of conversations) {
    if (c.inactive) continue;
    const id = c.id?.trim();
    if (!id) continue;
    if (isConversationOlderThanThreeDays(c, now)) ids.add(id);
  }
  return ids;
}

/** 分块计算默认选中，批间 yield，避免长列表阻塞 JS 主线程 */
export async function buildDefaultBatchCompleteSelectionAsync(
  conversations: MockConversation[],
  opts?: {
    chunkSize?: number;
    shouldContinue?: () => boolean;
  },
): Promise<Set<string>> {
  const chunkSize = opts?.chunkSize ?? BATCH_SELECTION_CHUNK_SIZE;
  const shouldContinue = opts?.shouldContinue ?? (() => true);
  const ids = new Set<string>();
  const now = new Date();

  for (let i = 0; i < conversations.length; i += 1) {
    if (!shouldContinue()) break;

    const c = conversations[i];
    if (!c.inactive) {
      const id = c.id?.trim();
      if (id && isConversationOlderThanThreeDays(c, now)) ids.add(id);
    }

    if (i > 0 && (i + 1) % chunkSize === 0) {
      await yieldToMainThread();
    }
  }

  return ids;
}

export function useBatchCompleteSessions(conversations: MockConversation[]) {
  const [batchSelectMode, setBatchSelectMode] = useState(false);
  const [batchPreparing, setBatchPreparing] = useState(false);
  const [selectedTaskIds, setSelectedTaskIds] = useState<Set<string>>(() => new Set());
  const [batchCompleting, setBatchCompleting] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const batchRefreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  /** 递增以取消尚未完成的异步默认选中 */
  const batchSelectGenRef = useRef(0);

  useEffect(() => {
    return () => {
      if (batchRefreshTimerRef.current) {
        clearTimeout(batchRefreshTimerRef.current);
        batchRefreshTimerRef.current = null;
      }
    };
  }, []);

  const scheduleClaimedListRefresh = useCallback(() => {
    if (batchRefreshTimerRef.current) clearTimeout(batchRefreshTimerRef.current);
    batchRefreshTimerRef.current = setTimeout(() => {
      batchRefreshTimerRef.current = null;
      void refreshClaimedConversations();
    }, BATCH_COMPLETE_REFRESH_DELAY_MS);
  }, []);

  const startBatchSelect = useCallback(() => {
    const gen = ++batchSelectGenRef.current;
    setBatchSelectMode(true);
    setBatchPreparing(true);
    setSelectedTaskIds(new Set());

    void (async () => {
      // 先让批量模式 UI（FlatList + checkbox）完成首帧渲染
      await yieldToMainThread();
      if (gen !== batchSelectGenRef.current) return;

      await afterInteractions();
      if (gen !== batchSelectGenRef.current) return;

      const ids = await buildDefaultBatchCompleteSelectionAsync(conversations, {
        shouldContinue: () => gen === batchSelectGenRef.current,
      });
      if (gen !== batchSelectGenRef.current) return;

      setSelectedTaskIds(ids);
      setBatchPreparing(false);
    })();
  }, [conversations]);

  const resetBatchSelect = useCallback(() => {
    batchSelectGenRef.current += 1;
    setBatchSelectMode(false);
    setBatchPreparing(false);
    setSelectedTaskIds(new Set());
    setConfirmOpen(false);
    setProgress(null);
  }, []);

  const cancelBatchSelect = useCallback(() => {
    if (batchCompleting) return;
    resetBatchSelect();
  }, [batchCompleting, resetBatchSelect]);

  const cancelBatchConfirm = useCallback(() => {
    if (batchCompleting) return;
    setConfirmOpen(false);
    setProgress(null);
  }, [batchCompleting]);

  const confirmBatchComplete = useCallback(async () => {
    if (batchCompleting) return;
    const taskIDs = [...selectedTaskIds].map((id) => id.trim()).filter(Boolean);
    if (!taskIDs.length) return;

    setBatchCompleting(true);
    const total = taskIDs.length;
    setProgress({ done: 0, total });

    let okCount = 0;
    let failCount = 0;
    try {
      for (const taskID of taskIDs) {
        try {
          await completeTask(taskID, 'resolved');
          okCount += 1;
        } catch {
          failCount += 1;
        }
        setProgress({ done: okCount + failCount, total });
      }
      setConfirmOpen(false);
      setProgress(null);
      resetBatchSelect();
      if (okCount > 0) {
        scheduleClaimedListRefresh();
      }
      if (failCount === 0) {
        appAlert('已提交', `已提交结束 ${okCount} 个会话，等待结果…`);
      } else {
        appAlert(
          '部分失败',
          `成功提交 ${okCount} 个，失败 ${failCount} 个。失败项请稍后重试。`,
        );
      }
    } finally {
      setBatchCompleting(false);
    }
  }, [batchCompleting, resetBatchSelect, scheduleClaimedListRefresh, selectedTaskIds]);

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

  const handleBatchActionPress = useCallback(() => {
    if (batchCompleting || confirmOpen || batchPreparing) return;
    if (!batchSelectMode) {
      const hasActive = conversations.some((c) => !c.inactive && c.id?.trim());
      if (!hasActive) {
        appAlert('提示', '当前没有可结束的活跃会话');
        return;
      }
      startBatchSelect();
      return;
    }

    const taskIDs = [...selectedTaskIds];
    if (!taskIDs.length) {
      appAlert('提示', '请至少选择一个会话');
      return;
    }

    setConfirmOpen(true);
  }, [
    batchCompleting,
    batchPreparing,
    batchSelectMode,
    confirmOpen,
    conversations,
    selectedTaskIds,
    startBatchSelect,
  ]);

  const batchConfirmModalProps = useMemo<BatchCompleteConfirmModalProps>(
    () => ({
      visible: confirmOpen,
      total: progress?.total ?? selectedTaskIds.size,
      done: progress?.done ?? 0,
      completing: batchCompleting,
      onCancel: cancelBatchConfirm,
      onConfirm: () => {
        void confirmBatchComplete();
      },
    }),
    [
      batchCompleting,
      cancelBatchConfirm,
      confirmBatchComplete,
      confirmOpen,
      progress,
      selectedTaskIds.size,
    ],
  );

  return {
    batchSelectMode,
    batchPreparing,
    selectedTaskIds,
    batchCompleting,
    batchConfirmModalProps,
    startBatchSelect,
    cancelBatchSelect,
    toggleBatchSelection,
    handleBatchActionPress,
  };
}
