// ============================================================
// 聊天房会话态：门禁 / 提示条 / 红黄点 / 导航展示 / 任务上下文
//
// 把原先散落在 [id].tsx 顶部的一堆 useState + claimed 列表订阅收拢到这里，
// 并通过稳定的 roomRef 把 setters / refs 暴露给 Ownership / Messages / Gateway。
// ============================================================
import { useCallback, useEffect, useRef, useState } from 'react';
import type { RefObject } from 'react';
import type { AdoptionContext, TaskMode } from '@/core/im';
import type { IMTaskSession, ProactiveActionHint } from '@/core/im/types';
import {
  clearActiveChatSession,
  setActiveChatImConversationID,
  setActiveChatTaskID,
} from '@/chatMessage/room/active-chat-session';
import {
  ensureClaimedConversationsHydrated,
  getClaimedConversationsSnapshot,
  hasVisibleConversationProactiveHint,
  hasVisibleConversationRedDot,
  pickPendingAdoptionContext,
  subscribeConversationChange,
  subscribeOtherConversationIndicators,
} from '@/lib/claimed-conversations-store';
import { pickValidProactiveActionHints } from '@/lib/proactive-action-hints';
import type { ChatInputGate } from '@/chatMessage/room/chat-input-gate';
import type { MockConversation } from '@/mock/data';
import {
  createEmptyChatRoomHandle,
  type ChatRoomHandle,
  type ChatTaskContext,
} from '@/chatMessage/room/chat-room-handle';

export function useChatRoomSession(opts: { taskID: string; supervisorParam: boolean }) {
  const { taskID, supervisorParam } = opts;

  const roomRef = useRef<ChatRoomHandle>(createEmptyChatRoomHandle(taskID));
  roomRef.current.taskID = taskID;

  // ---- refs（归属/消息/事件共用，挂到 room）----
  const ctxRef = useRef<ChatTaskContext>({
    conversationID: '',
    actorPlatformID: '',
    audiencePlatformID: '',
  });
  const seenRef = useRef<Set<string>>(new Set());
  const pendingSendKeysRef = useRef<string[]>([]);
  const lastServerMessageRef = useRef(roomRef.current.lastServerMessageRef.current);
  const localOnlyHistoryRef = useRef(false);
  const chatInitialLoadingRef = useRef(true);
  const taskModeRef = useRef<TaskMode | null>(null);
  const skillGroupRef = useRef<string | null>(null);

  roomRef.current.ctxRef = ctxRef;
  roomRef.current.seenRef = seenRef;
  roomRef.current.pendingSendKeysRef = pendingSendKeysRef;
  roomRef.current.lastServerMessageRef = lastServerMessageRef;
  roomRef.current.localOnlyHistoryRef = localOnlyHistoryRef;
  roomRef.current.chatInitialLoadingRef = chatInitialLoadingRef;
  roomRef.current.taskModeRef = taskModeRef;
  roomRef.current.skillGroupRef = skillGroupRef;

  // ---- 门禁 / 任务元数据 / 提示 ----
  const [inputGate, setInputGate] = useState<ChatInputGate>(
    supervisorParam ? { phase: 'supervisor_browse' } : { phase: 'ready' },
  );
  const [taskAnnotatorID, setTaskAnnotatorID] = useState<string | null>(null);
  const [taskMode, setTaskModeState] = useState<TaskMode | null>(null);
  // 进房首帧就从缓存取 skillGroup：labor 会话在 tasks/detail 返回前门禁也不会先按非 labor 走
  const [skillGroup, setSkillGroup] = useState<string | null>(() => {
    const conv = getClaimedConversationsSnapshot().find((c) => c.id === taskID);
    return conv?.skillGroup?.trim() || null;
  });
  const [adoptionContext, setAdoptionContext] = useState<AdoptionContext | null>(null);
  const [proactiveActionHints, setProactiveActionHints] = useState<ProactiveActionHint[] | null>(
    () => {
      const conv = getClaimedConversationsSnapshot().find((c) => c.id === taskID);
      return pickValidProactiveActionHints(conv?.proactiveActionHints) ?? null;
    },
  );
  const [adoptionModalOpen, setAdoptionModalOpen] = useState(false);
  const [currentHasRedDot, setCurrentHasRedDot] = useState(() => {
    const conv = getClaimedConversationsSnapshot().find((c) => c.id === taskID);
    return !!conv?.hasRedDot;
  });

  useEffect(() => {
    taskModeRef.current = taskMode;
  }, [taskMode]);

  useEffect(() => {
    skillGroupRef.current = skillGroup;
  }, [skillGroup]);

  // ---- 导航展示 ----
  const [taskTitle, setTaskTitle] = useState<string | null>(null);
  const [actorAvatarUrl, setActorAvatarUrl] = useState('');
  const [audienceAvatarUrl, setAudienceAvatarUrl] = useState('');
  const [audienceAvatarColor, setAudienceAvatarColor] = useState(() => {
    const conv = getClaimedConversationsSnapshot().find((c) => c.id === taskID);
    return conv?.avatarColor?.trim() || '';
  });
  const [actorNickname, setActorNickname] = useState('');
  const [audienceNickname, setAudienceNickname] = useState('');
  const [chatImConversationID, setChatImConversationID] = useState('');

  // ---- 其它会话红/黄点 ----
  const [otherConvHasRedDot, setOtherConvHasRedDot] = useState(() =>
    hasVisibleConversationRedDot(getClaimedConversationsSnapshot(), { taskID }),
  );
  const [otherConvHasYellowDot, setOtherConvHasYellowDot] = useState(() =>
    hasVisibleConversationProactiveHint(getClaimedConversationsSnapshot(), { taskID }),
  );

  const applyChatImConversationID = useCallback((id: string) => {
    const trimmed = id?.trim() || '';
    ctxRef.current.conversationID = trimmed;
    setChatImConversationID(trimmed);
    setActiveChatImConversationID(trimmed);
  }, []);

  const applyConversationDisplay = useCallback((conv: MockConversation) => {
    setTaskTitle(conv.audiencePlatformNickname?.trim() || conv.to || '会话');
    setAudienceAvatarUrl(conv.audiencePlatformFaceURL?.trim() || '');
    const color = conv.avatarColor?.trim();
    if (color) setAudienceAvatarColor(color);
    setActorNickname(conv.actorPlatformNickname?.trim() || conv.from || '');
    setAudienceNickname(conv.audiencePlatformNickname?.trim() || conv.to || '');
  }, []);

  /** tasks/detail.session 或本地缓存 session → 导航/气泡头像昵称 */
  const applyTaskSessionDisplay = useCallback((session: IMTaskSession) => {
    const actorName = session.actorPlatformNickname?.trim() || '';
    const audienceName = session.audiencePlatformNickname?.trim() || '';
    if (audienceName) {
      setTaskTitle(audienceName);
    }
    if (actorName) setActorNickname(actorName);
    if (audienceName) setAudienceNickname(audienceName);
    const actorFace = session.actorPlatformFaceURL?.trim() || '';
    const audienceFace = session.audiencePlatformFaceURL?.trim() || '';
    if (actorFace) setActorAvatarUrl(actorFace);
    if (audienceFace) setAudienceAvatarUrl(audienceFace);
    const audienceId = session.audiencePlatformID?.trim() || '';
    const actorId = session.actorPlatformID?.trim() || '';
    if (audienceId) ctxRef.current.audiencePlatformID = audienceId;
    if (actorId) ctxRef.current.actorPlatformID = actorId;
  }, []);

  // 挂稳定 setters / 动作到 room（每轮 refresh 动作指针）
  const room = roomRef.current;
  room.setInputGate = setInputGate;
  room.setTaskAnnotatorID = setTaskAnnotatorID;
  room.setTaskModeState = setTaskModeState;
  room.setSkillGroup = setSkillGroup;
  room.setAdoptionContext = setAdoptionContext;
  room.setAdoptionModalOpen = setAdoptionModalOpen;
  room.setProactiveActionHints = setProactiveActionHints;
  room.setCurrentHasRedDot = setCurrentHasRedDot;
  room.applyChatImConversationID = applyChatImConversationID;
  room.applyConversationDisplay = applyConversationDisplay;
  room.applyTaskSessionDisplay = applyTaskSessionDisplay;

  // 其它会话红/黄点（排除当前会话；不订阅全量列表）
  useEffect(() => {
    void ensureClaimedConversationsHydrated();
    const imConversationID = chatImConversationID.trim() || undefined;
    const off = subscribeOtherConversationIndicators({ taskID, imConversationID }, (flags) => {
      setOtherConvHasRedDot(flags.hasRedDot);
      setOtherConvHasYellowDot(flags.hasYellowDot);
    });
    return off;
  }, [taskID, chatImConversationID]);

  // 当前会话缓存变更：复审/黄条/红点/skillGroup（单会话订阅）
  useEffect(() => {
    const imID = chatImConversationID.trim();
    if (!imID) return;
    void ensureClaimedConversationsHydrated();
    const off = subscribeConversationChange(
      imID,
      (conv) => {
        if (!conv) return;
        setProactiveActionHints(pickValidProactiveActionHints(conv.proactiveActionHints) ?? null);
        setAdoptionContext(
          pickPendingAdoptionContext(conv.adoptionContext, { taskID, imConversationID: imID }),
        );
        setCurrentHasRedDot(!!conv.hasRedDot);
        const cachedSkillGroup = conv.skillGroup?.trim();
        if (cachedSkillGroup) setSkillGroup(cachedSkillGroup);
        const color = conv.avatarColor?.trim();
        if (color) setAudienceAvatarColor(color);
      },
    );
    return off;
  }, [taskID, chatImConversationID]);

  // 进房立刻记下 taskID（imConversationID 可能稍后才到）；离开时清空
  useEffect(() => {
    setActiveChatTaskID(taskID || null);
    return () => clearActiveChatSession();
  }, [taskID]);

  return {
    roomRef: roomRef as RefObject<ChatRoomHandle>,
    // refs（个别 hook 仍需直接拿）
    ctxRef,
    seenRef,
    pendingSendKeysRef,
    lastServerMessageRef,
    localOnlyHistoryRef,
    chatInitialLoadingRef,
    taskModeRef,
    skillGroupRef,
    // state
    inputGate,
    setInputGate,
    taskAnnotatorID,
    taskMode,
    setTaskModeState,
    skillGroup,
    setSkillGroup,
    adoptionContext,
    setAdoptionContext,
    proactiveActionHints,
    setProactiveActionHints,
    adoptionModalOpen,
    setAdoptionModalOpen,
    currentHasRedDot,
    setCurrentHasRedDot,
    taskTitle,
    setTaskTitle,
    actorAvatarUrl,
    setActorAvatarUrl,
    audienceAvatarUrl,
    setAudienceAvatarUrl,
    audienceAvatarColor,
    actorNickname,
    setActorNickname,
    audienceNickname,
    setAudienceNickname,
    chatImConversationID,
    otherConvHasRedDot,
    otherConvHasYellowDot,
    applyChatImConversationID,
    applyConversationDisplay,
    applyTaskSessionDisplay,
  };
}
