import { useCallback, useEffect, useMemo, useState, type RefObject } from 'react';
import { appAlert } from '@/lib/app-alert';
import { showToast } from '@/lib/app-toast';
import { subscribeConversationListManualRefresh } from '@/lib/conversation-list-refresh-bus';
import { resolveAudienceApiPlatform } from '@/core/im';
import { getClaimedConversationsSnapshot } from '@/lib/claimed-conversations-store';
import { pickValidProactiveActionHints } from '@/lib/proactive-action-hints';
import { copyImage, copyText } from '@/lib/clipboard';
import { openChatFileAttachment } from '@/chatMessage/message/open-attachment';
import { addCustomSticker } from '@/chatMessage/stickerPack';
import type { ChatInputAreaHandle } from '@/chatMessage/components/ChatInputArea';
import type { MediaPreviewState } from '@/chatMessage/components/MediaPreviewModal';
import type {
  MessageActionId,
  MessageActionKind,
  MessageActionMenuAnchor,
} from '@/chatMessage/components/MessageActionMenu.types';
import type { ChatMessageListHandle } from '@/chatMessage/list';
import {
  deriveChatInputUi,
  isChatInputOpen,
  isLaborSkillGroup,
  type ChatInputGate,
} from '@/chatMessage/room/chat-input-gate';
import {
  clearChatDraft,
  getChatDraft,
  setChatDraft,
} from '@/chatMessage/room/chat-draft-store';
import { useAiReplyCooldown } from '@/chatMessage/room/useAiReplyCooldown';
import { useChatGatewayEvents } from '@/chatMessage/room/useChatGatewayEvents';
import { useChatOwnership } from '@/chatMessage/room/useChatOwnership';
import { useChatRoomMessages } from '@/chatMessage/room/useChatRoomMessages';
import { useChatRoomSession } from '@/chatMessage/room/useChatRoomSession';
import { useChatSend } from '@/chatMessage/room/useChatSend';
import { useChatTaskActions } from '@/chatMessage/room/useChatTaskActions';
import { useKeyboardOffset } from '@/chatMessage/room/useKeyboardOffset';

/**
 * 聊天页业务 + 交互接线（不含排版）。
 * 桌面 / 手机 UI 共用这一份。
 */
export function useChatRoomScreen(opts: {
  taskID: string;
  annotatorId?: string;
  supervisorParam: boolean;
  messageListRef: RefObject<ChatMessageListHandle | null>;
  inputAreaRef: RefObject<ChatInputAreaHandle | null>;
  /** 主管接管成功并完成进房同步后回调（如标注员页跳转聊天模块） */
  onSupervisorTakeoverComplete?: (taskID: string) => void;
}) {
  const {
    taskID,
    annotatorId,
    supervisorParam,
    messageListRef,
    inputAreaRef,
    onSupervisorTakeoverComplete,
  } = opts;

  const session = useChatRoomSession({ taskID, supervisorParam });
  const { roomRef } = session;

  const {
    isSupervisorView,
    isSupervisorViewRef,
    currentSubjectAnnotatorId,
  } = useChatOwnership({
    roomRef,
    annotatorIdParam: annotatorId,
    supervisorParam,
    chatImConversationID: session.chatImConversationID,
    onSupervisorTakeoverComplete,
  });

  const {
    messages,
    setMessages,
    loading,
    loadingMore,
    hasMoreBefore,
    handleLoadOlder,
    scrollToEnd,
    reenterConversation,
  } = useChatRoomMessages({
    roomRef,
    messageListRef,
    isSupervisorViewRef,
    currentSubjectAnnotatorId,
    setTaskTitle: session.setTaskTitle,
    setActorAvatarUrl: session.setActorAvatarUrl,
    setAudienceAvatarUrl: session.setAudienceAvatarUrl,
    setActorNickname: session.setActorNickname,
    setAudienceNickname: session.setAudienceNickname,
  });

  const scrollToEndOnKeyboard = useCallback(() => {
    messageListRef.current?.scrollToEnd({ animated: false });
    setTimeout(() => messageListRef.current?.scrollToEnd({ animated: true }), 120);
    setTimeout(() => messageListRef.current?.scrollToEnd({ animated: true }), 320);
  }, [messageListRef]);

  const { keyboardOffset, keyboardVisible, nudgeKeyboardLift } = useKeyboardOffset({
    onKeyboardShow: scrollToEndOnKeyboard,
  });

  const dismissComposer = useCallback(() => {
    inputAreaRef.current?.dismissKeyboard();
  }, [inputAreaRef]);

  useChatGatewayEvents(roomRef);

  // 会话列表手动刷新完成后，按「重新进房」走同一套活跃/置灰/主管旁观逻辑
  useEffect(() => {
    return subscribeConversationListManualRefresh(() => {
      if (roomRef.current.takeoverInProgressRef.current) return;
      reenterConversation();
    });
  }, [roomRef, reenterConversation]);

  // 草稿放在外部 store，由 composer 自己订阅：打字不再触发整页重渲染
  const draftRoomKey = taskID;
  const setDraft = useCallback(
    (next: string | ((prev: string) => string)) => setChatDraft(draftRoomKey, next),
    [draftRoomKey],
  );
  const getDraft = useCallback(() => getChatDraft(draftRoomKey), [draftRoomKey]);
  useEffect(() => () => clearChatDraft(draftRoomKey), [draftRoomKey]);

  const [moreMenuOpen, setMoreMenuOpen] = useState(false);
  const [previewState, setPreviewState] = useState<MediaPreviewState>({ visible: false });
  const [actionMenu, setActionMenu] = useState<{
    kind: MessageActionKind;
    content: string;
    imageWidth?: number;
    imageHeight?: number;
    anchor: MessageActionMenuAnchor;
  } | null>(null);

  useEffect(() => {
    if (session.inputGate.phase === 'locked' && session.inputGate.hideMoreMenu) {
      setMoreMenuOpen(false);
    }
  }, [session.inputGate]);

  const closeMoreMenu = useCallback(() => setMoreMenuOpen(false), []);

  const laborSkillGroup = isLaborSkillGroup(session.skillGroup);

  const taskActions = useChatTaskActions({
    taskID,
    taskMode: session.taskMode,
    skillGroup: session.skillGroup,
    setInputGate: session.setInputGate,
    setTaskModeState: session.setTaskModeState,
    closeMoreMenu,
  });

  const openImageViewer = useCallback((uri: string) => {
    if (!uri) return;
    setPreviewState({ visible: true, kind: 'image', uri, fileName: '图片' });
  }, []);
  const openVideoViewer = useCallback((params: { uri: string; fileName?: string }) => {
    if (!params.uri) return;
    setPreviewState({ visible: true, kind: 'video', uri: params.uri, fileName: params.fileName || '视频' });
  }, []);
  const openFileViewer = useCallback((params: { uri: string; fileName: string }) => {
    if (!params.uri) return;
    void openChatFileAttachment({
      url: params.uri,
      fileName: params.fileName || '文件',
    }).catch((e) => {
      appAlert('打开失败', e instanceof Error ? e.message : '请稍后重试');
    });
  }, []);
  const closePreview = useCallback(() => {
    setPreviewState({ visible: false });
  }, []);

  const openMessageActionMenu = useCallback(
    (
      kind: MessageActionKind,
      content: string,
      rect: { x: number; y: number; width: number; height: number },
      opts?: {
        cursorX?: number;
        cursorY?: number;
        imageWidth?: number;
        imageHeight?: number;
      },
    ) => {
      if (!content) return;
      setActionMenu({
        kind,
        content,
        imageWidth: opts?.imageWidth,
        imageHeight: opts?.imageHeight,
        anchor: {
          top: rect.y,
          bottom: rect.y + rect.height,
          centerX: rect.x + rect.width / 2,
          cursorX: opts?.cursorX,
          cursorY: opts?.cursorY,
        },
      });
    },
    [],
  );

  const handleMessageAction = useCallback(
    async (id: MessageActionId) => {
      const menu = actionMenu;
      setActionMenu(null);
      if (!menu) return;

      if (id === 'add_sticker') {
        try {
          await addCustomSticker({
            url: menu.content,
            width: menu.imageWidth,
            height: menu.imageHeight,
          });
          showToast('已添加到表情', { variant: 'success' });
        } catch (e) {
          showToast(e instanceof Error ? e.message : '添加失败', { variant: 'danger' });
        }
        return;
      }

      if (id !== 'copy') return;
      if (menu.kind === 'image') {
        const ok = await copyImage(menu.content);
        if (!ok) appAlert('复制失败', '无法复制该图片，请稍后重试');
      } else {
        await copyText(menu.content);
      }
    },
    [actionMenu],
  );

  const handleOpenAudienceProfile = useCallback(() => {
    if (!taskID) return;
    const conv = getClaimedConversationsSnapshot().find(
      (c) =>
        c.id === taskID ||
        (!!session.chatImConversationID && c.imConversationID === session.chatImConversationID),
    );
    const audiencePlatformId =
      session.ctxRef.current.audiencePlatformID?.trim() ||
      conv?.audiencePlatformID?.trim() ||
      '';
    const imConversationID =
      session.chatImConversationID.trim() || conv?.imConversationID?.trim() || '';
    const platform = resolveAudienceApiPlatform({
      platform: typeof conv?.platform === 'string' ? conv.platform : undefined,
      imConversationID,
      audiencePlatformID: audiencePlatformId,
    });
    const nickname =
      session.audienceNickname.trim() ||
      conv?.audiencePlatformNickname?.trim() ||
      conv?.to?.trim() ||
      '';
    const avatar =
      session.audienceAvatarUrl.trim() ||
      conv?.audiencePlatformFaceURL?.trim() ||
      '';

    void platform;
    void nickname;
    void avatar;
  }, [taskID, session.chatImConversationID, session.audienceNickname, session.audienceAvatarUrl, session.ctxRef]);

  // labor 技能组：对方刚发来消息的 90s 内先留给 AI 应答，仅提示倒计时、不锁输入
  const { endAt: aiReplyCooldownEndAt, release: releaseAiReplyCooldown } = useAiReplyCooldown({
    taskID,
    messages,
    enabled: laborSkillGroup && session.inputGate.phase === 'ready',
  });
  const inputGate = useMemo<ChatInputGate>(
    () =>
      aiReplyCooldownEndAt == null
        ? session.inputGate
        : { phase: 'ai_reply_cooldown', endAt: aiReplyCooldownEndAt },
    [session.inputGate, aiReplyCooldownEndAt],
  );

  const send = useChatSend({
    taskID,
    ctxRef: session.ctxRef,
    inputGate,
    isSupervisorView,
    getDraft,
    setDraft,
    setMessages,
    scrollToEnd,
    inputAreaRef,
    lastServerMessageRef: session.lastServerMessageRef,
    pendingSendKeysRef: session.pendingSendKeysRef,
    adoptionContext: session.adoptionContext,
    setAdoptionContext: session.setAdoptionContext,
    setAdoptionModalOpen: session.setAdoptionModalOpen,
    setProactiveActionHints: session.setProactiveActionHints,
    releaseAiReplyCooldown,
  });

  const navTitle = session.taskTitle ?? `任务 ${taskID.slice(0, 8)}`;
  const inputUi = deriveChatInputUi(inputGate, { laborSkillGroup });
  const needsAdoptionReview =
    inputUi.allowAdoptionReview &&
    !!session.adoptionContext?.candidates &&
    session.adoptionContext.candidates.length > 0;
  const showProactiveHintBanner =
    !!pickValidProactiveActionHints(session.proactiveActionHints)?.length;

  return {
    session,
    messages,
    loading,
    loadingMore,
    hasMoreBefore,
    handleLoadOlder,
    keyboardOffset,
    keyboardVisible,
    nudgeKeyboardLift,
    dismissComposer,
    draftRoomKey,
    setDraft,
    moreMenuOpen,
    setMoreMenuOpen,
    closeMoreMenu,
    previewState,
    closePreview,
    actionMenu,
    setActionMenu,
    openImageViewer,
    openVideoViewer,
    openFileViewer,
    openMessageActionMenu,
    handleMessageAction,
    handleOpenAudienceProfile,
    ...taskActions,
    ...send,
    navTitle,
    ...inputUi,
    laborSkillGroup,
    needsAdoptionReview,
    showProactiveHintBanner,
    isChatInputOpen: isChatInputOpen(inputGate),
  };
}
