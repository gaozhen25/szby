// ============================================================
// 聊天房句柄：一间聊天页共享的 refs / setters / 意图动作。
//
// 各 hook 通过稳定的 RefObject<ChatRoomHandle> 读写，
// 每轮 render 由页面把最新函数挂到 .current，避免把 20 个 setter
// 塞进依赖数组（这正是此前 useChatMessages 拆分失败的根因）。
// ============================================================
import type { Dispatch, RefObject, SetStateAction } from 'react';
import type { AdoptionContext, IMServerMessage, TaskMode } from '@/core/im';
import type { IMTaskSession, ProactiveActionHint } from '@/core/im/types';
import type { ChatInputGate } from '@/chatMessage/room/chat-input-gate';
import type { DisplayMessage } from '@/chatMessage/message/chat-message-model';
import type { TakeoverTaskContext } from '@/lib/supervisor-takeover';
import type { MockConversation } from '@/mock/data';

export type ChatTaskContext = {
  conversationID: string;
  actorPlatformID: string;
  audiencePlatformID: string;
};

export type ChatRoomHandle = {
  taskID: string;

  // ---- 稳定 refs ----
  ctxRef: RefObject<ChatTaskContext>;
  seenRef: RefObject<Set<string>>;
  /**
   * 本地发出中的 clientMsgID 队列（FIFO）。
   * submit_result 按发送顺序配对，避免多条并发时总命中第一条 sending。
   */
  pendingSendKeysRef: RefObject<string[]>;
  lastServerMessageRef: RefObject<IMServerMessage | null>;
  localOnlyHistoryRef: RefObject<boolean>;
  chatInitialLoadingRef: RefObject<boolean>;
  taskModeRef: RefObject<TaskMode | null>;
  /** task.skillGroup（labor 等同 AI 托管），供 WS 事件派生门禁 */
  skillGroupRef: RefObject<string | null>;
  isSupervisorViewRef: RefObject<boolean>;
  takeoverInProgressRef: RefObject<boolean>;

  // ---- setters（useState 返回值，引用稳定）----
  setInputGate: Dispatch<SetStateAction<ChatInputGate>>;
  setMessages: Dispatch<SetStateAction<DisplayMessage[]>>;
  setHasMoreBefore: Dispatch<SetStateAction<boolean>>;
  setTaskAnnotatorID: Dispatch<SetStateAction<string | null>>;
  setTaskModeState: Dispatch<SetStateAction<TaskMode | null>>;
  setSkillGroup: Dispatch<SetStateAction<string | null>>;
  setAdoptionContext: Dispatch<SetStateAction<AdoptionContext | null>>;
  setAdoptionModalOpen: Dispatch<SetStateAction<boolean>>;
  setProactiveActionHints: Dispatch<SetStateAction<ProactiveActionHint[] | null>>;
  setCurrentHasRedDot: Dispatch<SetStateAction<boolean>>;

  // ---- 每轮 render 刷新的动作（经 roomRef.current 调用，不进 deps）----
  applyChatImConversationID: (id: string) => void;
  applyConversationDisplay: (conv: MockConversation) => void;
  /** 用 tasks/detail 的 session（或本地缓存）刷新头像/昵称 */
  applyTaskSessionDisplay: (session: IMTaskSession) => void;
  trackLastServerMessage: (msg: IMServerMessage) => void;
  scrollToEnd: () => void;
  mergeServerMessages: (
    list: IMServerMessage[],
    opts?: { position?: 'append' | 'prepend' },
  ) => void;
  persistMessagesLocally: (list: IMServerMessage[]) => void;
  /** 重拉当前会话：detail → by_conversation；自持写缓存并解锁输入，旁观只刷新展示 */
  reloadConversationAsOwner: () => Promise<void>;
  currentSubjectAnnotatorId: () => string;

  // ---- 归属意图（Ownership 挂载；Gateway 只调这两个）----
  enterOwnerAfterTakeover: (ctx?: TakeoverTaskContext) => Promise<void>;
  enterSupervisorBrowseAfterReturn: () => void;
};

/** 创建空壳，由各 hook 在首轮 render 填满 */
export function createEmptyChatRoomHandle(taskID: string): ChatRoomHandle {
  const noop = () => {};
  const asyncNoop = async () => {};
  return {
    taskID,
    ctxRef: { current: { conversationID: '', actorPlatformID: '', audiencePlatformID: '' } },
    seenRef: { current: new Set() },
    pendingSendKeysRef: { current: [] },
    lastServerMessageRef: { current: null },
    localOnlyHistoryRef: { current: false },
    chatInitialLoadingRef: { current: true },
    taskModeRef: { current: null },
    skillGroupRef: { current: null },
    isSupervisorViewRef: { current: false },
    takeoverInProgressRef: { current: false },
    setInputGate: noop as ChatRoomHandle['setInputGate'],
    setMessages: noop as ChatRoomHandle['setMessages'],
    setHasMoreBefore: noop as ChatRoomHandle['setHasMoreBefore'],
    setTaskAnnotatorID: noop as ChatRoomHandle['setTaskAnnotatorID'],
    setTaskModeState: noop as ChatRoomHandle['setTaskModeState'],
    setSkillGroup: noop as ChatRoomHandle['setSkillGroup'],
    setAdoptionContext: noop as ChatRoomHandle['setAdoptionContext'],
    setAdoptionModalOpen: noop as ChatRoomHandle['setAdoptionModalOpen'],
    setProactiveActionHints: noop as ChatRoomHandle['setProactiveActionHints'],
    setCurrentHasRedDot: noop as ChatRoomHandle['setCurrentHasRedDot'],
    applyChatImConversationID: noop,
    applyConversationDisplay: noop,
    applyTaskSessionDisplay: noop,
    trackLastServerMessage: noop,
    scrollToEnd: noop,
    mergeServerMessages: noop,
    persistMessagesLocally: noop,
    reloadConversationAsOwner: asyncNoop,
    currentSubjectAnnotatorId: () => '',
    enterOwnerAfterTakeover: asyncNoop,
    enterSupervisorBrowseAfterReturn: noop,
  };
}
