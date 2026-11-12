// ============================================================
// 手机端在线新消息提醒
// - 前台、非当前会话：状态栏下方横幅 + 提示音
// - 正在看同一会话：不提醒
// - 后台：系统横幅 + 系统提示音
// Web 页签隐藏仍走 web-incoming-alert
// ============================================================
import { AppState, Platform } from 'react-native';

import { isLoggedIn, getRole } from '@/core/auth';
import { getAgentId, getChatService, previewFromServerMessage } from '@/core/im';
import type { IMGatewayEvent, IMServerMessage, IMTaskContext } from '@/core/im';
import { isActiveChatConversation } from '@/chatMessage/room/active-chat-session';
import { isConversationOwnedAndActive } from '@/chatMessage/room/chat-input-gate';
import {
  findConversationIndexByIdentity,
  isPlaceholderConversationName,
} from '@/lib/claimed-conversations-merge';
import {
  getClaimedConversationsSnapshot,
  isConversationAdoptionHandled,
} from '@/lib/claimed-conversations-store';
import { discardIfStaleAiReviewRequired } from '@/lib/ai-review-freshness';
import type { MockConversation } from '@/mock/data';

import { playNativeIncomingFeedback } from './incoming-alert-sound';
import { dismissIncomingBanner, showIncomingBanner } from './incoming-banner';
import { presentIncomingLocalNotification } from './local-notification';
import { resolvePushAvatarUrl } from './resolve-push-avatar-url';
import {
  initWebIncomingAlert,
  resetWebIncomingAlertUi,
} from './web-incoming-alert';

const DEDUPE_TTL_MS = 30_000;

let started = false;
let disposeFn: (() => void) | null = null;
let lastNotifyAt = 0;
const seenKeys = new Map<string, number>();

function pruneSeen(now: number): void {
  if (seenKeys.size < 80) return;
  for (const [k, t] of seenKeys) {
    if (now - t > DEDUPE_TTL_MS) seenKeys.delete(k);
  }
}

function consumeDedupeKey(key: string): boolean {
  const now = Date.now();
  pruneSeen(now);
  const prev = seenKeys.get(key);
  if (prev && now - prev < DEDUPE_TTL_MS) return true;
  seenKeys.set(key, now);
  return false;
}

function isAppInBackground(): boolean {
  if (Platform.OS === 'web') return false;
  return AppState.currentState !== 'active';
}

function matchConversation(
  imConversationID?: string,
  taskID?: string,
): MockConversation | undefined {
  const list = getClaimedConversationsSnapshot();
  const idx = findConversationIndexByIdentity(list, {
    imConversationID,
    id: taskID ?? '',
  });
  return idx >= 0 ? list[idx] : undefined;
}

function resolveSenderName(
  ctx: IMTaskContext | undefined,
  conv: MockConversation | undefined,
): string {
  const candidates = [
    ctx?.audiencePlatformNickname,
    conv?.audiencePlatformNickname,
    conv?.to,
  ];
  for (const name of candidates) {
    const n = name?.trim();
    if (n && !isPlaceholderConversationName(n)) return n;
  }
  return '新消息';
}

function isAiReviewGatewayEvent(evt: IMGatewayEvent): boolean {
  if (evt.type === 'ai_review_required') return true;
  return evt.type === 'annotation_event' && evt.event?.eventType === 8;
}

function resolveAiReviewBody(evt: IMGatewayEvent): string {
  const adoption =
    evt.type === 'ai_review_required' || evt.type === 'annotation_event'
      ? evt.event?.adoptionContext
      : undefined;
  const count = Array.isArray(adoption?.candidates) ? adoption.candidates.length : 0;
  return count > 0
    ? `有 AI 消息需要人工复审（${count} 条候选）`
    : '有 AI 消息需要人工复审';
}

function handleAiReviewAlert(evt: IMGatewayEvent): void {
  if (!isAiReviewGatewayEvent(evt)) return;
  if (getRole() === 'supervisor') return;

  const event =
    evt.type === 'ai_review_required' || evt.type === 'annotation_event'
      ? evt.event
      : undefined;
  const taskContext =
    evt.type === 'ai_review_required' || evt.type === 'annotation_event'
      ? evt.task_context
      : undefined;

  const annotatorID = event?.annotatorID;
  if (annotatorID && annotatorID !== getAgentId()) return;

  const imConversationID = taskContext?.imConversationID?.trim();
  const taskID = (taskContext?.taskID ?? event?.taskID)?.trim();
  const conv = matchConversation(imConversationID, taskID);
  if (conv && !isConversationOwnedAndActive(conv)) return;

  if (
    evt.type === 'ai_review_required' &&
    discardIfStaleAiReviewRequired(
      {
        lastTriggerMsgID: taskContext?.lastTriggerMsgID,
        convLastServerMsgID: conv?.lastMessage?.serverMsgID,
        taskID,
        imConversationID,
      },
      { stage: 'native_push_alert', eventID: event?.eventID ?? null },
    )
  ) {
    return;
  }

  if (
    isConversationAdoptionHandled({
      taskID,
      imConversationID,
      adoptionID: event?.adoptionContext?.adoptionID,
    })
  ) {
    return;
  }

  const viewingThisChat =
    !isAppInBackground() && isActiveChatConversation(imConversationID, taskID);
  if (viewingThisChat) return;

  const key = event?.eventID?.trim() || event?.adoptionContext?.adoptionID?.trim() || '';
  if (key && consumeDedupeKey(`ai-review:${key}`)) return;

  const now = Date.now();
  if (now - lastNotifyAt < 500) return;
  lastNotifyAt = now;

  const title = resolveSenderName(taskContext, conv);
  const body = resolveAiReviewBody(evt);
  const avatarUrl =
    taskContext?.audiencePlatformFaceURL?.trim() ||
    conv?.audiencePlatformFaceURL?.trim();

  if (isAppInBackground()) {
    presentIncomingLocalNotification({
      title,
      body,
      taskID: taskID || '',
      avatarUrl: resolvePushAvatarUrl(avatarUrl),
    });
    return;
  }

  playNativeIncomingFeedback();
  showIncomingBanner({
    title,
    body,
    avatarUrl: resolvePushAvatarUrl(avatarUrl),
    taskID,
  });
}

function handleGatewayEvent(evt: IMGatewayEvent): void {
  if (Platform.OS === 'web') return;
  if (!isLoggedIn()) return;

  if (isAiReviewGatewayEvent(evt)) {
    handleAiReviewAlert(evt);
    return;
  }

  if (evt.type !== 'annotation_event') return;
  if (evt.event?.eventType !== 1) return;

  const msg: IMServerMessage | undefined = evt.event?.message;
  if (!msg || msg.direction !== 0) return;

  const annotatorID = evt.event?.annotatorID;
  if (annotatorID && annotatorID !== getAgentId()) return;

  const imConversationID = evt.task_context?.imConversationID?.trim();
  const taskID = (evt.task_context?.taskID ?? evt.event?.taskID)?.trim();
  const conv = matchConversation(imConversationID, taskID);
  if (conv && !isConversationOwnedAndActive(conv)) return;

  const viewingThisChat =
    !isAppInBackground() && isActiveChatConversation(imConversationID, taskID);
  if (viewingThisChat) return;

  const key = evt.event?.eventID?.trim() || msg.serverMsgID?.trim() || '';
  if (key && consumeDedupeKey(key)) return;

  const now = Date.now();
  if (now - lastNotifyAt < 500) return;
  lastNotifyAt = now;

  const title = resolveSenderName(evt.task_context, conv);
  const body = previewFromServerMessage(msg);
  const avatarUrl =
    evt.task_context?.audiencePlatformFaceURL?.trim() ||
    conv?.audiencePlatformFaceURL?.trim();

  if (isAppInBackground()) {
    presentIncomingLocalNotification({
      title,
      body,
      taskID: taskID || '',
      avatarUrl: resolvePushAvatarUrl(avatarUrl),
    });
    return;
  }

  playNativeIncomingFeedback();
  showIncomingBanner({
    title,
    body,
    avatarUrl: resolvePushAvatarUrl(avatarUrl),
    taskID,
  });
}

/** 根布局常驻：Web + 原生在线提醒。幂等。 */
export function initIncomingMessageAlert(): () => void {
  if (started) return disposeIncomingMessageAlert;
  started = true;

  const offWeb = initWebIncomingAlert();
  const offNative = getChatService().onGatewayEvent(handleGatewayEvent);

  disposeFn = () => {
    offNative();
    offWeb();
    resetIncomingMessageAlertUi();
    disposeFn = null;
    started = false;
  };

  return disposeIncomingMessageAlert;
}

export function disposeIncomingMessageAlert(): void {
  disposeFn?.();
}

export function resetIncomingMessageAlertUi(): void {
  resetWebIncomingAlertUi();
  dismissIncomingBanner();
  lastNotifyAt = 0;
  seenKeys.clear();
}
