// ============================================================
// 聊天房消息域：列表状态 + merge/去重 + 进房初始化 + 分页 + 自持重载
//
// Web / 移动端共用（useChatRoomScreen → [id].tsx / ChatRoomPane）：
// - 活跃会话：有本地消息缓存则先展示（最多 20 条），后台 tasks/detail + 远端同步
// - detail 12s 超时后用列表缓存降级
//
// 与 Ownership 的接缝：reloadConversationAsOwner 挂到 roomRef，
// 接管/归还命中 claimed/list 后由 Ownership 调用，不再反向传 setter。
// ============================================================
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { RefObject } from 'react';
import {
  getAgentId,
  getChatService,
  getTaskSessionInfo,
  isOutgoingServerMessage,
  normalizeSendTimeMs,
  parseApiMessageContent,
  preserveServerMessageForCache,
} from '@/core/im';
import type { IMServerMessage } from '@/core/im';
import { fetchMessagesByConversation, fetchTaskDetail } from '@/api/tasks';
import { waitForAuthBootstrap } from '@/core/auth-flow';
import {
  ensureClaimedConversationsHydrated,
  getClaimedConversationsSnapshot,
  pickPendingAdoptionContext,
  setConversationAdoptionContext,
  updateConversationTaskMode,
} from '@/lib/claimed-conversations-store';
import { pickValidProactiveActionHints } from '@/lib/proactive-action-hints';
import {
  gateForOwnedActive,
  inactiveConversationGate,
} from '@/chatMessage/room/chat-input-gate';
import {
  displayLastMessageSignature,
  displayToLastServerMessage,
  toDisplay,
  type DisplayMessage,
} from '@/chatMessage/message/chat-message-model';
import {
  loadLatestChatMessages,
  loadOlderChatMessages,
  peekLatestChatMessagesFromMemory,
  prefetchChatMessagesToMemory,
  upsertChatMessages,
  upsertChatTaskSession,
} from '@/chatMessage/message/chat-messages-cache';
import {
  appendOutboxToMessages,
  outboxGetPendingKeys,
} from '@/chatMessage/message/chat-pending-outbox';
import {
  flushConversationLastMessage,
  scheduleConversationLastMessage,
} from '@/lib/conversation-last-message-bus';
import type { ChatRoomHandle } from '@/chatMessage/room/chat-room-handle';
import type { ChatMessageListHandle } from '@/chatMessage/list';
import type { MockConversation } from '@/mock/data';

const TASK_DETAIL_TIMEOUT_MS = 12_000;
/** 进房本地首屏条数（与 messages/by_conversation showNumber 对齐） */
const LOCAL_BOOTSTRAP_LIMIT = 20;

function hasCachedMessagesForTask(taskID: string): boolean {
  const cached = getClaimedConversationsSnapshot().find((c) => c.id === taskID);
  const im = cached?.imConversationID?.trim();
  if (!im) return false;
  return peekLatestChatMessagesFromMemory(im, LOCAL_BOOTSTRAP_LIMIT).messages.length > 0;
}

async function fetchTaskDetailWithTimeout(
  taskID: string,
  opts: { annotatorID?: string; messageLimit?: number } = {},
): Promise<Awaited<ReturnType<typeof fetchTaskDetail>> | null> {
  try {
    return await Promise.race([
      fetchTaskDetail(taskID, opts),
      new Promise<null>((resolve) => {
        setTimeout(() => resolve(null), TASK_DETAIL_TIMEOUT_MS);
      }),
    ]);
  } catch {
    return null;
  }
}

function applyCachedConversationFallback(
  room: ChatRoomHandle,
  cached: MockConversation,
  taskID: string,
  supervisorView: boolean,
): void {
  room.applyConversationDisplay(cached);
  const im = cached.imConversationID?.trim();
  if (im) {
    room.applyChatImConversationID(im);
    room.ctxRef.current.audiencePlatformID = cached.audiencePlatformID?.trim() || '';
  }
  if (cached.skillGroup?.trim()) room.setSkillGroup(cached.skillGroup.trim());
  if (supervisorView) {
    room.setInputGate({ phase: 'supervisor_browse' });
    return;
  }
  if (cached.inactive) {
    room.localOnlyHistoryRef.current = true;
    room.setInputGate(inactiveConversationGate(cached));
    room.setProactiveActionHints(pickValidProactiveActionHints(cached.proactiveActionHints) ?? null);
    room.setTaskModeState(cached.taskMode ?? null);
    return;
  }
  if (cached.returnedToAgent) {
    room.setInputGate({ phase: 'locked', reason: '已归还给原客服', hideMoreMenu: true });
  } else if (cached.supervisorTakeover) {
    room.setInputGate({
      phase: 'locked',
      reason: '会话已被主管接管，暂不可发送',
      hideMoreMenu: true,
    });
  } else {
    room.setInputGate(
      gateForOwnedActive({
        taskMode: cached.taskMode ?? 'human',
        skillGroup: cached.skillGroup?.trim() || null,
      }),
    );
  }
  room.setProactiveActionHints(pickValidProactiveActionHints(cached.proactiveActionHints) ?? null);
  room.setAdoptionContext(
    pickPendingAdoptionContext(cached.adoptionContext, {
      taskID,
      imConversationID: im,
    }),
  );
  room.setTaskModeState(cached.taskMode ?? null);
}

type BootstrapLocalHistoryParams = {
  room: ChatRoomHandle;
  imConversationID: string;
  mergeServerMessages: (
    list: IMServerMessage[],
    mergeOpts?: { position?: 'append' | 'prepend' },
  ) => void;
  setHasMoreBefore: (v: boolean) => void;
};

/** 读本地消息缓存并合并进列表；有消息时返回 true */
async function bootstrapLocalHistory(params: BootstrapLocalHistoryParams): Promise<boolean> {
  const im = params.imConversationID.trim();
  if (!im) return false;
  const local = await loadLatestChatMessages(im, LOCAL_BOOTSTRAP_LIMIT);
  if (local.session) params.room.applyTaskSessionDisplay(local.session);
  if (local.messages.length) {
    params.mergeServerMessages(local.messages, { position: 'prepend' });
    params.setHasMoreBefore(local.hasMoreBefore);
    return true;
  }
  if (local.hasMoreBefore) params.setHasMoreBefore(true);
  return false;
}

function pickLastMessageForList(
  lastDisplay: DisplayMessage | undefined,
  lastServer: IMServerMessage | null,
): IMServerMessage | null {
  if (!lastDisplay) return lastServer;
  const fromDisplay = displayToLastServerMessage(lastDisplay);
  if (!lastServer) return fromDisplay;
  const displayTime = normalizeSendTimeMs(fromDisplay.sendTime);
  const serverTime = normalizeSendTimeMs(lastServer.sendTime);
  if (displayTime > serverTime) return fromDisplay;
  return lastServer;
}

/** 远端快照覆盖列表（进房同步 / 接管重载）；不经过 seenRef 增量 merge */
function buildDisplayFromServerMessages(
  room: ChatRoomHandle,
  list: IMServerMessage[],
  actor: string,
  trackLast: (m: IMServerMessage) => void,
): DisplayMessage[] {
  room.seenRef.current.clear();
  room.pendingSendKeysRef.current = [];
  room.lastServerMessageRef.current = null;
  const display: DisplayMessage[] = [];
  for (const m of list) {
    const id = m.serverMsgID?.trim();
    if (id) {
      if (room.seenRef.current.has(id)) continue;
      room.seenRef.current.add(id);
    }
    trackLast(m);
    display.push(toDisplay(m, actor));
  }
  return display;
}

export function useChatRoomMessages(opts: {
  roomRef: RefObject<ChatRoomHandle>;
  messageListRef: RefObject<ChatMessageListHandle | null>;
  /** 进房初始化用：读取进入时视角，运行时切换不重跑 effect */
  isSupervisorViewRef: RefObject<boolean>;
  currentSubjectAnnotatorId: () => string;
  /** 进房时写导航标题/头像（detail 成功路径） */
  setTaskTitle: (v: string | null) => void;
  setActorAvatarUrl: (v: string) => void;
  setAudienceAvatarUrl: (v: string) => void;
  setActorNickname: (v: string) => void;
  setAudienceNickname: (v: string) => void;
}) {
  const {
    roomRef,
    messageListRef,
    isSupervisorViewRef,
    currentSubjectAnnotatorId,
    setTaskTitle,
    setActorAvatarUrl,
    setAudienceAvatarUrl,
    setActorNickname,
    setAudienceNickname,
  } = opts;

  const taskID = roomRef.current.taskID;
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [loading, setLoading] = useState(() => !hasCachedMessagesForTask(taskID));
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMoreBefore, setHasMoreBefore] = useState(false);
  /** 手动刷新会话列表等：再跑一遍进房，不整页重挂 */
  const [enterEpoch, setEnterEpoch] = useState(0);
  const reenterConversation = useCallback(() => {
    setEnterEpoch((n) => n + 1);
  }, []);

  // messages 最新引用，供 loadOlder 读最早一条，避免把 messages 放进 deps 导致回调抖动
  const messagesRef = useRef(messages);
  messagesRef.current = messages;
  const loadingMoreRef = useRef(false);
  const hasMoreBeforeRef = useRef(false);
  hasMoreBeforeRef.current = hasMoreBefore;
  /** 本次进房是否已从本地缓存展示首屏（内存/磁盘） */
  const cacheRevealedRef = useRef(false);
  /** revealFromCache 已处理过的末条 key；prepend 加载历史时末条不变，不应再滚到底 */
  const lastRevealTailKeyRef = useRef('');

  roomRef.current.setMessages = setMessages;
  roomRef.current.setHasMoreBefore = setHasMoreBefore;

  const scrollToEnd = useCallback(() => {
    setTimeout(() => messageListRef.current?.scrollToEnd({ animated: true }), 120);
  }, [messageListRef]);

  const trackLastServerMessage = useCallback((msg: IMServerMessage) => {
    const prev = roomRef.current.lastServerMessageRef.current;
    const nextTime = normalizeSendTimeMs(msg.sendTime);
    const prevTime = prev ? normalizeSendTimeMs(prev.sendTime) : 0;
    if (!prev || nextTime >= prevTime) {
      roomRef.current.lastServerMessageRef.current = preserveServerMessageForCache(msg);
    }
  }, [roomRef]);

  const mergeServerMessages = useCallback(
    (list: IMServerMessage[], mergeOpts: { position?: 'append' | 'prepend' } = {}) => {
      const { position = 'append' } = mergeOpts;
      const room = roomRef.current;
      const actor = room.ctxRef.current.actorPlatformID;
      for (const m of list) {
        if (m?.serverMsgID) trackLastServerMessage(m);
      }
      setMessages((prev) => {
        let working = prev;
        const incoming: DisplayMessage[] = [];
        const batchSeen = new Set<string>();
        for (const m of list) {
          const id = m.serverMsgID?.trim();
          if (id) {
            if (room.seenRef.current.has(id) || batchSeen.has(id)) continue;
            // submit_result 已把本地 key 升成 serverMsgID，但 seenRef 偶发未跟上时也要挡掉
            if (working.some((x) => x.key === id || x.serverMsgID === id)) {
              room.seenRef.current.add(id);
              continue;
            }
          }

          // 我方发出：优先就地升级对应的乐观气泡，避免先双份再被 submit_result 去重闪成一条
          if (id && isOutgoingServerMessage(m, actor)) {
            const clientMsgID = m.clientMsgID?.trim();
            const text =
              m.contentType === 101 || m.contentType == null
                ? parseApiMessageContent(m.content).trim()
                : '';
            let matchIdx = -1;
            if (clientMsgID) {
              matchIdx = working.findIndex(
                (x) =>
                  x.status === 'sending' &&
                  (x.clientMsgID === clientMsgID || x.key === clientMsgID),
              );
            }
            if (matchIdx < 0 && text) {
              matchIdx = working.findIndex(
                (x) => x.status === 'sending' && x.mine && x.kind === 'text' && x.text === text,
              );
            }
            if (matchIdx >= 0) {
              const local = working[matchIdx];
              const localClient = local.clientMsgID || local.key;
              // 不在这里消费 pending 队列：留给 submit_result 按发送顺序 pop，避免双通道各消费一次错位
              working = working.map((x, i) =>
                i === matchIdx
                  ? {
                      ...x,
                      status: 'sent' as const,
                      serverMsgID: id,
                      clientMsgID: localClient,
                      key: id,
                    }
                  : x,
              );
              batchSeen.add(id);
              room.seenRef.current.add(id);
              continue;
            }
          }

          if (id) {
            batchSeen.add(id);
            room.seenRef.current.add(id);
          }
          incoming.push(toDisplay(m, actor));
        }
        if (!incoming.length) {
          return appendOutboxToMessages(room.taskID, working);
        }
        const merged =
          position === 'prepend' ? [...incoming, ...working] : [...working, ...incoming];
        return appendOutboxToMessages(room.taskID, merged);
      });
    },
    [roomRef, trackLastServerMessage],
  );

  /** by_conversation 等远端快照：整表替换，避免本地 seenRef 挡住同步 */
  const replaceRemoteSnapshot = useCallback(
    (
      list: IMServerMessage[],
      hasMore: boolean,
      _opts: { preserveSending?: boolean } = {},
    ) => {
      if (!list.length) return;
      const room = roomRef.current;
      const actor = room.ctxRef.current.actorPlatformID;
      const display = buildDisplayFromServerMessages(room, list, actor, trackLastServerMessage);
      setMessages(appendOutboxToMessages(room.taskID, display));
      setHasMoreBefore(hasMore);
      scrollToEnd();
    },
    [roomRef, trackLastServerMessage, scrollToEnd],
  );

  const persistMessagesLocally = useCallback(
    (list: IMServerMessage[]) => {
      if (roomRef.current.isSupervisorViewRef.current) return;
      const imConversationID = roomRef.current.ctxRef.current.conversationID?.trim();
      if (!imConversationID || !list.length) return;
      void upsertChatMessages(imConversationID, list);
    },
    [roomRef],
  );

  /**
   * 重拉当前会话：tasks/detail → messages/by_conversation。
   * 客服自持会写缓存并解锁输入区；主管旁观只刷新展示，不改门禁/缓存。
   */
  const reloadConversationAsOwner = useCallback(async () => {
    const room = roomRef.current;
    const supervisorView = room.isSupervisorViewRef.current;
    const annotatorID = currentSubjectAnnotatorId();

    const detail = await fetchTaskDetailWithTimeout(room.taskID, {
      messageLimit: 1,
      annotatorID,
    });
    if (!detail?.task) return;

    const info = getTaskSessionInfo(detail.task);
    const convID = info.imConversationID?.trim();
    if (!convID) return;

    room.applyChatImConversationID(convID);
    room.ctxRef.current.actorPlatformID = info.actorPlatformID;
    room.ctxRef.current.audiencePlatformID = info.audiencePlatformID;

    if (detail.task.session) {
      room.applyTaskSessionDisplay(detail.task.session);
    }

    if (!supervisorView) {
      room.localOnlyHistoryRef.current = false;
      if (detail.task.session) {
        void upsertChatTaskSession(convID, detail.task.session);
      }

      room.setTaskAnnotatorID(detail.task.annotatorID ?? null);
      const mode = detail.task.taskMode ?? 'human';
      const skillGroup = detail.task.skillGroup?.trim() || null;
      room.setTaskModeState(mode);
      room.setSkillGroup(skillGroup);
      updateConversationTaskMode({
        taskID: room.taskID,
        imConversationID: convID,
        taskMode: mode,
        skillGroup: skillGroup ?? undefined,
      });

      const conv = getClaimedConversationsSnapshot().find(
        (c) => c.imConversationID === convID || c.id === room.taskID,
      );
      const match = { taskID: room.taskID, imConversationID: convID };
      // 优先读会话缓存中的 adoptionContext；detail 仅兜底并回写缓存
      const fromCache = pickPendingAdoptionContext(conv?.adoptionContext, match);
      const fromDetail = pickPendingAdoptionContext(detail.task.adoptionContext, match);
      const pending = fromCache ?? fromDetail;
      room.setAdoptionContext(pending);
      if (!fromCache && fromDetail) {
        void setConversationAdoptionContext({ ...match, adoptionContext: fromDetail });
      }
      room.setProactiveActionHints(
        pickValidProactiveActionHints(conv?.proactiveActionHints) ?? null,
      );

      const ownedByMe = !detail.task.annotatorID || detail.task.annotatorID === getAgentId();
      if (ownedByMe) {
        room.setInputGate(gateForOwnedActive({ taskMode: mode, skillGroup }));
      }
    }

    const latest = detail.messages?.length
      ? detail.messages[detail.messages.length - 1]
      : undefined;

    let remoteMessages: IMServerMessage[] = [];
    let hasMore = false;

    if (latest?.serverMsgID) {
      const his = await fetchMessagesByConversation({
        conversationID: convID,
        annotatorID,
        anchorServerMsgID: latest.serverMsgID,
        anchorDirection: 1,
        includeAnchor: true,
        showNumber: 20,
      }).catch(() => null);

      if (his?.messages?.length) {
        remoteMessages = his.messages;
        hasMore = his.hasMoreBefore ?? false;
      } else if (latest) {
        remoteMessages = [latest];
      }
    } else if (latest) {
      remoteMessages = [latest];
    }

    if (!remoteMessages.length) return;

    replaceRemoteSnapshot(remoteMessages, hasMore, { preserveSending: false });
    if (!supervisorView) {
      void upsertChatMessages(convID, remoteMessages);
    }
  }, [roomRef, replaceRemoteSnapshot, currentSubjectAnnotatorId]);

  // 每轮把消息域动作挂到 room
  {
    const room = roomRef.current;
    room.trackLastServerMessage = trackLastServerMessage;
    room.scrollToEnd = scrollToEnd;
    room.mergeServerMessages = mergeServerMessages;
    room.persistMessagesLocally = persistMessagesLocally;
    room.reloadConversationAsOwner = reloadConversationAsOwner;
    room.currentSubjectAnnotatorId = currentSubjectAnnotatorId;
  }

  /** 锚点分页：置灰只翻本地；活跃优先接口（失败降级本地）；旁观只走接口 */
  const loadOlderMessages = useCallback(async () => {
    const room = roomRef.current;
    const convID = room.ctxRef.current.conversationID;
    if (!convID || loadingMoreRef.current || !hasMoreBeforeRef.current) return;

    const earliest = messagesRef.current.find((m) => m.serverMsgID);
    if (!earliest?.serverMsgID) return;

    loadingMoreRef.current = true;
    setLoadingMore(true);
    messageListRef.current?.lockScrollForPrepend();
    const supervisorView = room.isSupervisorViewRef.current;
    let prepended = false;
    try {
      if (!supervisorView && room.localOnlyHistoryRef.current) {
        const local = await loadOlderChatMessages(convID, {
          anchorServerMsgID: earliest.serverMsgID,
          limit: 10,
        });
        if (local.messages.length) {
          messageListRef.current?.prepareForPrepend();
          mergeServerMessages(local.messages, { position: 'prepend' });
          prepended = true;
        }
        setHasMoreBefore(local.hasMoreBefore);
        return;
      }

      try {
        const res = await fetchMessagesByConversation({
          conversationID: convID,
          annotatorID: room.currentSubjectAnnotatorId(),
          anchorServerMsgID: earliest.serverMsgID,
          anchorDirection: 1,
          includeAnchor: false,
          showNumber: 20,
        });
        if (res.messages?.length) {
          messageListRef.current?.prepareForPrepend();
          mergeServerMessages(res.messages, { position: 'prepend' });
          prepended = true;
          if (!supervisorView) {
            void upsertChatMessages(convID, res.messages);
          }
        }
        setHasMoreBefore(res.hasMoreBefore ?? false);
      } catch {
        if (supervisorView) return;
        const local = await loadOlderChatMessages(convID, {
          anchorServerMsgID: earliest.serverMsgID,
          limit: 10,
        });
        if (local.messages.length) {
          messageListRef.current?.prepareForPrepend();
          mergeServerMessages(local.messages, { position: 'prepend' });
          prepended = true;
        }
        setHasMoreBefore(local.hasMoreBefore);
      }
    } finally {
      loadingMoreRef.current = false;
      setLoadingMore(false);
      if (!prepended) messageListRef.current?.releasePrependLock();
    }
  }, [roomRef, messageListRef, mergeServerMessages]);

  const handleLoadOlder = useCallback(() => {
    void loadOlderMessages();
  }, [loadOlderMessages]);

  const lastListSigRef = useRef('');
  const lastListPrimedRef = useRef(false);

  const publishRoomLastMessage = useCallback(
    (mode: 'schedule' | 'flush') => {
      const room = roomRef.current;
      if (room.isSupervisorViewRef.current) return;
      const imConversationID = room.ctxRef.current.conversationID?.trim();
      if (!imConversationID) return;
      const lastMessage = pickLastMessageForList(
        messagesRef.current[messagesRef.current.length - 1],
        room.lastServerMessageRef.current,
      );
      if (!lastMessage) {
        if (mode === 'flush') flushConversationLastMessage(imConversationID);
        return;
      }
      if (mode === 'flush') {
        flushConversationLastMessage(imConversationID, lastMessage);
        return;
      }
      scheduleConversationLastMessage({ imConversationID, lastMessage });
    },
    [roomRef],
  );

  // 进房完成后，末条变化（发送乐观消息 / 回执 / 入站）再回写会话列表；历史 prepend 不改末条签名
  useEffect(() => {
    const room = roomRef.current;
    if (loading || room.chatInitialLoadingRef.current) {
      lastListPrimedRef.current = false;
      return;
    }
    const last = messages[messages.length - 1];
    const sig = displayLastMessageSignature(last);
    if (!lastListPrimedRef.current) {
      lastListPrimedRef.current = true;
      lastListSigRef.current = sig;
      return;
    }
    if (sig === lastListSigRef.current) return;
    lastListSigRef.current = sig;
    publishRoomLastMessage('schedule');
  }, [loading, messages, publishRoomLastMessage, roomRef]);

  // 进房首屏：同步读内存缓存，避免二次进房先闪 loading（Web / 移动端共用）
  useLayoutEffect(() => {
    cacheRevealedRef.current = false;
    lastRevealTailKeyRef.current = '';
    setMessages([]);
    setHasMoreBefore(false);
    const room = roomRef.current;
    const supervisorView = isSupervisorViewRef.current;
    room.seenRef.current.clear();
    room.pendingSendKeysRef.current = outboxGetPendingKeys(taskID);
    const cached = getClaimedConversationsSnapshot().find((c) => c.id === taskID);
    const im = cached?.imConversationID?.trim() || '';

    if (cached) {
      applyCachedConversationFallback(room, cached, taskID, supervisorView);
    }
    if (im) prefetchChatMessagesToMemory(im);

    const peek = im ? peekLatestChatMessagesFromMemory(im, LOCAL_BOOTSTRAP_LIMIT) : null;
    if (peek?.messages.length) {
      mergeServerMessages(peek.messages, { position: 'prepend' });
      setHasMoreBefore(peek.hasMoreBefore);
      room.chatInitialLoadingRef.current = false;
      setLoading(false);
      cacheRevealedRef.current = true;
      messageListRef.current?.revealFromCache();
    } else {
      setLoading(true);
    }
    setMessages((prev) => appendOutboxToMessages(taskID, prev));
  }, [taskID, enterEpoch, mergeServerMessages, messageListRef, roomRef, isSupervisorViewRef]);

  // loading 结束且首屏有消息时去掉遮罩（messageListRef 可能晚于数据就绪）
  // 注意：加载更早消息 prepend 时 messages.length 也会增加，但末条 key 不变，不能滚到底
  useEffect(() => {
    if (loading || messages.length === 0) return;
    const tailKey = messages[messages.length - 1]?.key ?? '';
    if (tailKey && tailKey === lastRevealTailKeyRef.current) return;
    lastRevealTailKeyRef.current = tailKey;
    messageListRef.current?.revealFromCache();
  }, [loading, messages.length, messages, messageListRef]);

  // 进房初始化：后台拉 detail / 远端消息，合并覆盖本地缓存
  useEffect(() => {
    let alive = true;
    const room = roomRef.current;
    const supervisorView = isSupervisorViewRef.current;
    const annotatorId = currentSubjectAnnotatorId();

    if (!cacheRevealedRef.current) {
      room.seenRef.current.clear();
      room.pendingSendKeysRef.current = [];
    }
    room.lastServerMessageRef.current = null;
    room.localOnlyHistoryRef.current = false;
    if (!cacheRevealedRef.current) {
      room.chatInitialLoadingRef.current = true;
      room.setTaskAnnotatorID(null);
      room.setTaskModeState(null);
      room.setAdoptionContext(null);
      room.setAdoptionModalOpen(false);
      room.setInputGate(supervisorView ? { phase: 'supervisor_browse' } : { phase: 'ready' });
    }

    const chat = getChatService();
    if (chat.getConnection().getState() !== 'connected') void chat.start();

    (async () => {
      let revealedLocally = cacheRevealedRef.current;
      let localBootstrappedIm: string | null = revealedLocally
        ? getClaimedConversationsSnapshot().find((c) => c.id === taskID)?.imConversationID?.trim() ||
          null
        : null;

      const revealFromLocalCache = () => {
        if (revealedLocally) return;
        revealedLocally = true;
        cacheRevealedRef.current = true;
        room.chatInitialLoadingRef.current = false;
        setLoading(false);
        messageListRef.current?.revealFromCache();
      };

      const tryBootstrapLocal = async (imConversationID: string): Promise<boolean> => {
        const im = imConversationID.trim();
        if (!im || localBootstrappedIm === im) return false;
        const hasMessages = await bootstrapLocalHistory({
          room,
          imConversationID: im,
          mergeServerMessages,
          setHasMoreBefore,
        });
        if (!alive) return false;
        localBootstrappedIm = im;
        if (hasMessages) revealFromLocalCache();
        return hasMessages;
      };

      let remoteOk = false;

      try {
        if (!(await waitForAuthBootstrap())) return;
        await ensureClaimedConversationsHydrated();
        const cached = getClaimedConversationsSnapshot().find((c) => c.id === taskID);
        if (alive && cached) {
          applyCachedConversationFallback(room, cached, taskID, supervisorView);
        } else if (alive && cached?.skillGroup?.trim()) {
          room.setSkillGroup(cached.skillGroup.trim());
        }

        if (!supervisorView && cached?.inactive) {
          const imConversationID = cached.imConversationID?.trim() || '';
          if (imConversationID && !revealedLocally) {
            await tryBootstrapLocal(imConversationID);
          }
          return;
        }

        const imFromCache = cached?.imConversationID?.trim() || '';
        if (imFromCache && !revealedLocally) {
          await tryBootstrapLocal(imFromCache);
        }

        const detail = await fetchTaskDetailWithTimeout(taskID, {
          messageLimit: 1,
          annotatorID: annotatorId,
        });

        if (!detail?.task && cached && alive) {
          const imFromCache = cached.imConversationID?.trim() || '';
          if (imFromCache && !room.ctxRef.current.conversationID?.trim()) {
            room.applyChatImConversationID(imFromCache);
          }
        }

        if (detail?.task) {
          const info = getTaskSessionInfo(detail.task);
          const detailSkillGroup = detail.task.skillGroup?.trim() || null;
          room.applyChatImConversationID(info.imConversationID);
          room.ctxRef.current.actorPlatformID = info.actorPlatformID;
          room.ctxRef.current.audiencePlatformID = info.audiencePlatformID;
          if (alive) {
            room.setTaskAnnotatorID(detail.task.annotatorID ?? null);
            const mode = detail.task.taskMode ?? 'human';
            room.setSkillGroup(detailSkillGroup);
            room.setTaskModeState(mode);
            setTaskTitle(info.audienceName || '会话');
            setActorAvatarUrl(info.actorAvatar?.trim() || '');
            setAudienceAvatarUrl(info.audienceAvatar?.trim() || '');
            setActorNickname(
              detail.task.session?.actorPlatformNickname?.trim() || info.actorName || '',
            );
            setAudienceNickname(
              detail.task.session?.audiencePlatformNickname?.trim() || info.audienceName || '',
            );
            if (detail.task.session && info.imConversationID && !supervisorView) {
              void upsertChatTaskSession(info.imConversationID, detail.task.session);
            }
            if (!supervisorView) {
              updateConversationTaskMode({
                taskID,
                imConversationID: info.imConversationID,
                taskMode: mode,
                skillGroup: detailSkillGroup ?? undefined,
              });
            }
            const conv = getClaimedConversationsSnapshot().find(
              (c) => c.imConversationID === info.imConversationID || c.id === taskID,
            );
            const match = { taskID, imConversationID: info.imConversationID };
            const fromCache = pickPendingAdoptionContext(conv?.adoptionContext, match);
            const fromDetail = pickPendingAdoptionContext(detail.task.adoptionContext, match);
            const pending = fromCache ?? fromDetail;
            room.setAdoptionContext(pending);
            if (!fromCache && fromDetail) {
              void setConversationAdoptionContext({ ...match, adoptionContext: fromDetail });
            }
            room.setProactiveActionHints(
              pickValidProactiveActionHints(conv?.proactiveActionHints) ?? null,
            );
          }

          const cacheReturned = Boolean(
            cached?.returnedToAgent ||
              getClaimedConversationsSnapshot().some((c) => c.id === taskID && c.returnedToAgent),
          );
          const cacheTakeover = Boolean(
            cached?.supervisorTakeover ||
              getClaimedConversationsSnapshot().some(
                (c) => c.id === taskID && c.supervisorTakeover,
              ),
          );

          if (supervisorView) {
            if (alive) room.setInputGate({ phase: 'supervisor_browse' });
          } else if (cacheReturned) {
            if (alive) {
              room.setInputGate({
                phase: 'locked',
                reason: '已归还给原客服',
                hideMoreMenu: true,
              });
              room.setAdoptionContext(null);
              room.setProactiveActionHints(null);
            }
          } else if (cacheTakeover) {
            if (alive) {
              room.setInputGate({
                phase: 'locked',
                reason: '会话已被主管接管，暂不可发送',
                hideMoreMenu: true,
              });
              room.setAdoptionContext(null);
              room.setProactiveActionHints(null);
            }
          } else if (detail.task.annotatorID && detail.task.annotatorID !== getAgentId()) {
            if (alive) {
              room.setInputGate({ phase: 'unavailable' });
              room.setAdoptionContext(null);
            }
          } else if (alive) {
            room.setInputGate(
              gateForOwnedActive({
                taskMode: detail.task.taskMode ?? 'human',
                skillGroup: detailSkillGroup,
              }),
            );
          }
        }

        const convID = room.ctxRef.current.conversationID?.trim() || '';
        if (convID && convID !== localBootstrappedIm) {
          await tryBootstrapLocal(convID);
        }

        const latest = detail?.messages?.length
          ? detail.messages[detail.messages.length - 1]
          : undefined;

        if (convID && latest?.serverMsgID && alive) {
          const his = await fetchMessagesByConversation({
            conversationID: convID,
            annotatorID: annotatorId,
            anchorServerMsgID: latest.serverMsgID,
            anchorDirection: 1,
            includeAnchor: true,
            showNumber: 20,
          }).catch(() => null);

          if (his?.messages?.length) {
            remoteOk = true;
            replaceRemoteSnapshot(his.messages, his.hasMoreBefore ?? false);
            if (!supervisorView) {
              void upsertChatMessages(convID, his.messages);
            }
          } else if (latest) {
            remoteOk = true;
            replaceRemoteSnapshot([latest], false);
            if (!supervisorView && convID) {
              void upsertChatMessages(convID, [latest]);
            }
          }
        } else if (latest && alive) {
          remoteOk = true;
          replaceRemoteSnapshot([latest], false);
          if (!supervisorView && convID) {
            void upsertChatMessages(convID, [latest]);
          }
        }

        if (!supervisorView && !remoteOk && convID && alive && !latest) {
          await tryBootstrapLocal(convID);
        }

        if (!supervisorView && !convID && alive) {
          const imFromList = cached?.imConversationID?.trim() || '';
          if (imFromList) {
            room.applyChatImConversationID(imFromList);
            if (cached) room.applyConversationDisplay(cached);
            await tryBootstrapLocal(imFromList);
          }
        }
      } finally {
        if (alive) {
          room.pendingSendKeysRef.current = outboxGetPendingKeys(room.taskID);
          setMessages((prev) => appendOutboxToMessages(room.taskID, prev));
          if (revealedLocally || remoteOk) {
            messageListRef.current?.revealFromCache();
          } else {
            messageListRef.current?.markInitialScrollPending();
          }
          room.chatInitialLoadingRef.current = false;
          setLoading(false);
        }
      }
    })();

    return () => {
      alive = false;
      publishRoomLastMessage('flush');
    };
    // 进房跟 taskID / enterEpoch 走；视角/主体取进入时快照（ref / 回调），运行时接管不重跑
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskID, enterEpoch]);

  return {
    messages,
    setMessages,
    loading,
    loadingMore,
    hasMoreBefore,
    handleLoadOlder,
    scrollToEnd,
    mergeServerMessages,
    persistMessagesLocally,
    trackLastServerMessage,
    reloadConversationAsOwner,
    reenterConversation,
  };
}
