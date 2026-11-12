// ============================================================
// 聊天页归属编排：主管旁观 ↔ 拥有者视角切换、接管 / 归还、claimed/list 缓存监听
//
// 对外只暴露意图：enterOwnerAfterTakeover / enterSupervisorBrowseAfterReturn。
// 门禁与消息重载一律经 roomRef 调用，不再接收 20 个 setter。
// ============================================================
import { useCallback, useEffect, useRef, useState } from 'react';
import type { RefObject } from 'react';
import { getAgentId } from '@/core/im';
import { getRole } from '@/core/auth';
import { fetchTaskDetail, supervisorEnterThread, supervisorExitThread } from '@/api/tasks';
import { fetchAdminTask } from '@/api/agents';
import { getAgentInfoById } from '@/lib/agent-info';
import {
  contextToTakeoverConversation,
  type TakeoverTaskContext,
} from '@/lib/supervisor-takeover';
import { taskToConversation } from '@/lib/task-session-list';
import {
  getClaimedConversationsSnapshot,
  pickPendingAdoptionContext,
  setConversationAdoptionContext,
  subscribeConversationChange,
  syncClaimedList,
  updateConversationTaskMode,
  upsertSupervisorTakeoverConversation,
} from '@/lib/claimed-conversations-store';
import { pickValidProactiveActionHints } from '@/lib/proactive-action-hints';
import {
  gateForOwnedActive,
  gateFromConversation,
  isConversationOwnedAndActive,
} from '@/chatMessage/room/chat-input-gate';
import type { ChatRoomHandle } from '@/chatMessage/room/chat-room-handle';
import type { MockConversation } from '@/mock/data';

export function useChatOwnership(opts: {
  roomRef: RefObject<ChatRoomHandle>;
  annotatorIdParam?: string;
  supervisorParam: boolean;
  chatImConversationID: string;
  onSupervisorTakeoverComplete?: (taskID: string) => void;
}) {
  const { roomRef, annotatorIdParam, supervisorParam, chatImConversationID, onSupervisorTakeoverComplete } =
    opts;
  const taskID = roomRef.current.taskID;

  const [isSupervisorView, setIsSupervisorView] = useState(supervisorParam);
  const isSupervisorViewRef = useRef(supervisorParam);
  useEffect(() => {
    isSupervisorViewRef.current = isSupervisorView;
  }, [isSupervisorView]);

  const takeoverInProgressRef = useRef(false);
  const refreshChatFromCacheChangeRef = useRef(false);

  roomRef.current.isSupervisorViewRef = isSupervisorViewRef;
  roomRef.current.takeoverInProgressRef = takeoverInProgressRef;

  const applySupervisorView = useCallback((next: boolean) => {
    isSupervisorViewRef.current = next;
    setIsSupervisorView(next);
  }, []);

  const currentSubjectAnnotatorId = useCallback(
    () => (isSupervisorViewRef.current && annotatorIdParam ? annotatorIdParam : getAgentId()),
    [annotatorIdParam],
  );
  roomRef.current.currentSubjectAnnotatorId = currentSubjectAnnotatorId;

  /** 主管旁观：进入聊天页订阅任务推送，离开页面取消订阅 */
  useEffect(() => {
    if (!isSupervisorView || !taskID) return;

    void supervisorEnterThread(taskID).catch((e) => {
      console.warn('[chat] supervisor enter_thread failed', e);
    });

    return () => {
      void supervisorExitThread(taskID).catch((e) => {
        console.warn('[chat] supervisor exit_thread failed', e);
      });
    };
  }, [isSupervisorView, taskID]);

  const persistSupervisorTakeover = useCallback(
    async (ctx?: TakeoverTaskContext) => {
      if (getRole() !== 'supervisor') return;
      const room = roomRef.current;

      const subject = currentSubjectAnnotatorId();
      const fromAgentId = subject && subject !== getAgentId() ? subject : undefined;
      const fromAgentAccount = fromAgentId
        ? (await getAgentInfoById(fromAgentId).catch(() => null))?.agent_accout?.trim() || undefined
        : undefined;

      const meta = { fromAgentId, fromAgentAccount };
      const fallbackIm =
        ctx?.imConversationID?.trim() || room.ctxRef.current.conversationID?.trim() || '';

      const res = await fetchAdminTask(taskID).catch(() => null);
      const takeoverCtx: TakeoverTaskContext | undefined = ctx
        ? { ...ctx, taskID: ctx.taskID?.trim() || taskID }
        : taskID
          ? { taskID, imConversationID: fallbackIm || undefined }
          : undefined;
      let conv = res?.ok && res.item
        ? taskToConversation(res.item, 0, meta)
        : takeoverCtx
          ? contextToTakeoverConversation(takeoverCtx, 0, meta)
          : null;
      if (!conv) return;

      // 服务端 task / task_context 常缺 taskID，必须用进房路由 taskID 兜底，否则列表 item.id.trim 会崩
      const resolvedId = (conv.id?.trim() || taskID || '').trim();
      if (!resolvedId && !conv.imConversationID?.trim() && !fallbackIm) {
        console.warn('[chat] 主管接管缺少 taskID/imConversationID，跳过 upsert');
        return;
      }
      conv = {
        ...conv,
        id: resolvedId || conv.id,
        imConversationID: conv.imConversationID?.trim() || fallbackIm || conv.imConversationID,
      };

      await upsertSupervisorTakeoverConversation(conv).catch(() => {});
    },
    [taskID, currentSubjectAnnotatorId, roomRef],
  );

  const refreshChatFromCacheChange = useCallback(async () => {
    const room = roomRef.current;
    const imID = room.ctxRef.current.conversationID?.trim();
    if (!imID) return;
    if (room.chatInitialLoadingRef.current) return;
    if (refreshChatFromCacheChangeRef.current) return;
    refreshChatFromCacheChangeRef.current = true;
    try {
      const conv = getClaimedConversationsSnapshot().find(
        (c) => c.imConversationID?.trim() === imID || c.id === taskID,
      );

      if (conv) {
        room.applyConversationDisplay(conv);
        room.setProactiveActionHints(
          pickValidProactiveActionHints(conv.proactiveActionHints) ?? null,
        );
        room.setCurrentHasRedDot(!!conv.hasRedDot);
      }

      if (!isConversationOwnedAndActive(conv)) {
        const derived = gateFromConversation(conv, {
          isSupervisorView: isSupervisorViewRef.current,
        });
        if (derived) {
          room.setInputGate(derived.gate);
          if (derived.clearHints) {
            room.setAdoptionContext(null);
            room.setProactiveActionHints(null);
          }
        }
        return;
      }

      const detail = await fetchTaskDetail(taskID, {
        messageLimit: 1,
        annotatorID: getAgentId(),
      }).catch(() => null);
      if (!detail?.task) {
        room.setInputGate(
          gateForOwnedActive({
            taskMode: conv.taskMode,
            skillGroup: conv.skillGroup ?? room.skillGroupRef.current,
          }),
        );
        return;
      }
      if (detail.task.annotatorID) room.setTaskAnnotatorID(detail.task.annotatorID);
      const mode = detail.task.taskMode ?? 'human';
      const skillGroup = detail.task.skillGroup?.trim() || null;
      room.setSkillGroup(skillGroup);
      if (mode === 'human' || mode === 'ai_assisted') {
        room.setTaskModeState(mode);
        updateConversationTaskMode({
          taskID,
          imConversationID: imID,
          taskMode: mode,
          skillGroup: skillGroup ?? undefined,
        });
      }

      if (detail.task.annotatorID && detail.task.annotatorID !== getAgentId()) {
        if (isSupervisorViewRef.current) {
          room.setInputGate({ phase: 'supervisor_browse' });
        } else {
          room.setInputGate({ phase: 'unavailable' });
          room.setAdoptionContext(null);
        }
        return;
      }

      // 优先读会话缓存 adoptionContext；detail 仅兜底并回写
      const match = { taskID, imConversationID: imID };
      const fromCache = pickPendingAdoptionContext(conv?.adoptionContext, match);
      const fromDetail = pickPendingAdoptionContext(detail.task.adoptionContext, match);
      const pending = fromCache ?? fromDetail;
      room.setAdoptionContext(pending);
      if (!fromCache && fromDetail) {
        void setConversationAdoptionContext({ ...match, adoptionContext: fromDetail });
      }
      room.setInputGate(gateForOwnedActive({ taskMode: mode, skillGroup }));
    } finally {
      refreshChatFromCacheChangeRef.current = false;
    }
  }, [taskID, roomRef]);

  const applyChatGateFromCache = useCallback(
    (conv: MockConversation | undefined) => {
      const room = roomRef.current;
      if (room.chatInitialLoadingRef.current) return;
      if (conv) {
        room.setProactiveActionHints(
          pickValidProactiveActionHints(conv.proactiveActionHints) ?? null,
        );
        room.setCurrentHasRedDot(!!conv.hasRedDot);
        const imConversationID = conv.imConversationID?.trim() || undefined;
        room.setAdoptionContext(
          pickPendingAdoptionContext(conv.adoptionContext, {
            taskID,
            imConversationID,
          }),
        );
      }
      const derived = gateFromConversation(conv, {
        isSupervisorView: isSupervisorViewRef.current,
      });
      if (!derived) return;
      room.setInputGate(derived.gate);
      if (derived.clearHints) {
        room.setAdoptionContext(null);
        room.setProactiveActionHints(null);
      }
    },
    [roomRef],
  );

  /** 意图：主管归还成功 → 切回旁观 */
  const enterSupervisorBrowseAfterReturn = useCallback(() => {
    const room = roomRef.current;
    applySupervisorView(true);
    room.localOnlyHistoryRef.current = false;
    room.setAdoptionContext(null);
    room.setProactiveActionHints(null);
    room.setInputGate({ phase: 'supervisor_browse' });
    const conv = getClaimedConversationsSnapshot().find(
      (c) => c.id === taskID || c.imConversationID === room.ctxRef.current.conversationID?.trim(),
    );
    const originalAnnotator = annotatorIdParam?.trim() || conv?.fromAgentId?.trim() || null;
    room.setTaskAnnotatorID(originalAnnotator);
  }, [applySupervisorView, taskID, annotatorIdParam, roomRef]);

  /** 意图：主管接管成功 → 等 claimed/list 命中后充当客服进房 */
  const enterOwnerAfterTakeover = useCallback(
    async (ctx?: TakeoverTaskContext) => {
      const room = roomRef.current;
      const imConversationID =
        ctx?.imConversationID?.trim() || room.ctxRef.current.conversationID?.trim() || undefined;
      takeoverInProgressRef.current = true;
      room.setInputGate({ phase: 'locked', reason: '接管中，正在同步会话…', hideMoreMenu: true });
      try {
        await persistSupervisorTakeover(ctx);
        const ok = await syncClaimedList({
          match: { taskID, imConversationID },
          grace: true,
          tag: 'chat.supervisor_takeover_result',
        });
        if (!ok) {
          room.setInputGate({
            phase: 'locked',
            reason: '接管超时，请下拉刷新后重试',
            hideMoreMenu: true,
          });
          return;
        }
        applySupervisorView(false);
        await room.reloadConversationAsOwner();
        onSupervisorTakeoverComplete?.(taskID);
      } finally {
        takeoverInProgressRef.current = false;
      }
    },
    [taskID, persistSupervisorTakeover, applySupervisorView, roomRef, onSupervisorTakeoverComplete],
  );

  roomRef.current.enterOwnerAfterTakeover = enterOwnerAfterTakeover;
  roomRef.current.enterSupervisorBrowseAfterReturn = enterSupervisorBrowseAfterReturn;

  // claimed/list 写缓存后的归属门禁变化
  useEffect(() => {
    const imID = chatImConversationID.trim();
    if (!imID) return;
    const off = subscribeConversationChange(
      imID,
      (conv, prev) => {
        const room = roomRef.current;
        if (room.chatInitialLoadingRef.current) return;
        if (takeoverInProgressRef.current) return;
        const wasOwned = isConversationOwnedAndActive(prev);
        const nowOwned = isConversationOwnedAndActive(conv);
        if (!wasOwned && nowOwned) {
          if (isSupervisorViewRef.current) {
            void refreshChatFromCacheChange();
          } else {
            void room.reloadConversationAsOwner();
          }
          return;
        }
        applyChatGateFromCache(conv);
      },
      { emitInitial: false },
    );
    return off;
  }, [
    chatImConversationID,
    refreshChatFromCacheChange,
    applyChatGateFromCache,
    roomRef,
  ]);

  return {
    isSupervisorView,
    isSupervisorViewRef,
    currentSubjectAnnotatorId,
  };
}
