// ============================================================
// Web 在线新消息提醒（仅浏览器）
// - 页签可见：应用内顶部横幅 + 提示音（窗口失焦时额外弹浏览器通知）
// - 页签隐藏：浏览器系统通知 + 标题闪烁 + 提示音
// - 回到应用页签：停止闪烁、关掉系统通知，标题恢复为应用名
// ============================================================
import { Image, Platform } from 'react-native';
import Constants from 'expo-constants';
import { router, type Href } from 'expo-router';

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
import { appAlert } from '@/lib/app-alert';
import type { MockConversation } from '@/mock/data';

import { showIncomingBanner } from './incoming-banner';

const APP_TITLE =
  (Constants.expoConfig?.extra?.appName as string) ||
  Constants.expoConfig?.name ||
  '轻回';
const FLASH_TEXT = '【新消息】';
const FLASH_TITLE = `${FLASH_TEXT}${APP_TITLE}`;
const FLASH_MS = 800;
const SOUND_THROTTLE_MS = 1500;
const DEDUPE_TTL_MS = 30_000;
const BANNER_TAG = 'qinghui-incoming-message';

let started = false;
let disposeFn: (() => void) | null = null;

let titleTimer: ReturnType<typeof setInterval> | null = null;
let showingFlash = false;

let audioEl: HTMLAudioElement | null = null;
let soundUnlocked = false;
let lastSoundAt = 0;
let lastBanner: Notification | null = null;
let notifyIconUri: string | null = null;
const seenKeys = new Map<string, number>();

/** 页签真正隐藏（切到别的标签 / 最小化）→ 走系统通知 */
function isTabHidden(): boolean {
  if (typeof document === 'undefined') return false;
  return document.visibilityState === 'hidden' || document.hidden === true;
}

/** 页签仍可见但窗口失焦（点到别的窗口 / DevTools） */
function isWindowUnfocused(): boolean {
  if (typeof document === 'undefined') return false;
  if (typeof document.hasFocus === 'function' && !document.hasFocus()) return true;
  return false;
}

/** 页签可见且窗口有焦点：正在看本应用 */
function isWebForeground(): boolean {
  return !isTabHidden() && !isWindowUnfocused();
}

function stopTitleFlash(): void {
  if (titleTimer) {
    clearInterval(titleTimer);
    titleTimer = null;
  }
  showingFlash = false;
  if (typeof document !== 'undefined') {
    document.title = APP_TITLE;
  }
}

function startTitleFlash(): void {
  if (typeof document === 'undefined') return;
  showingFlash = true;
  document.title = FLASH_TITLE;
  if (titleTimer) return;
  titleTimer = setInterval(() => {
    showingFlash = !showingFlash;
    document.title = showingFlash ? FLASH_TITLE : APP_TITLE;
  }, FLASH_MS);
}

function resolveAssetUri(mod: unknown): string {
  if (typeof mod === 'string') return mod;
  if (mod && typeof mod === 'object') {
    const rec = mod as { uri?: string; default?: unknown };
    if (typeof rec.uri === 'string' && rec.uri) return rec.uri;
    if (typeof rec.default === 'string' && rec.default) return rec.default;
  }
  try {
    return Image.resolveAssetSource(mod as number)?.uri ?? '';
  } catch {
    return '';
  }
}

function toAbsoluteUrl(uri: string): string {
  if (!uri) return '';
  if (/^(https?:|data:|blob:)/i.test(uri)) return uri;
  if (typeof window === 'undefined') return uri;
  try {
    return new URL(uri, window.location.href).href;
  } catch {
    return uri;
  }
}

function resolveSoundUri(): string {
  // Edge 对 mp3 兼容性通常优于 wav
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const mp3 = resolveAssetUri(require('../../../assets/newMsg.mp3'));
    if (mp3) return mp3;
  } catch {
    // ignore
  }
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const wav = resolveAssetUri(require('../../../assets/new_msg.wav'));
    if (wav) return wav;
  } catch {
    // ignore
  }
  return '';
}

function resolveNotifyIconUri(): string {
  if (notifyIconUri) return notifyIconUri;
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    notifyIconUri = toAbsoluteUrl(resolveAssetUri(require('../../../assets/images/icon-qinghui.png')));
  } catch {
    notifyIconUri = '';
  }
  return notifyIconUri;
}

function getAudio(): HTMLAudioElement | null {
  if (typeof Audio === 'undefined') return null;
  if (audioEl) return audioEl;
  const uri = resolveSoundUri();
  if (!uri) return null;
  audioEl = new Audio(uri);
  audioEl.preload = 'auto';
  audioEl.volume = 1;
  return audioEl;
}

async function unlockSound(): Promise<void> {
  if (soundUnlocked) return;
  const audio = getAudio();
  if (!audio) return;
  try {
    await audio.play();
    audio.pause();
    audio.currentTime = 0;
    soundUnlocked = true;
  } catch {
    // 浏览器未手势解锁时会失败，等下次交互再试
  }
}

function playNotifySound(): void {
  const now = Date.now();
  if (now - lastSoundAt < SOUND_THROTTLE_MS) return;
  lastSoundAt = now;
  const audio = getAudio();
  if (!audio) return;
  try {
    audio.currentTime = 0;
  } catch {
    // ignore
  }
  void audio.play().then(() => {
    soundUnlocked = true;
  }).catch(() => {
    // 未解锁时静默失败；首次点击后即可出声
  });
}

function isSecureContext(): boolean {
  if (typeof window === 'undefined') return false;
  return window.isSecureContext === true;
}

function canUseBanner(): boolean {
  return typeof Notification !== 'undefined' && isSecureContext();
}

/** 诊断 Web 系统通知不可用的原因（供设置页 / 调试） */
export function getWebNotificationBlockReason(): string | null {
  if (Platform.OS !== 'web') return null;
  if (typeof Notification === 'undefined') {
    if (!isSecureContext()) {
      return '当前为 HTTP 访问，Edge/Chrome 不允许系统通知。请改用 HTTPS，或在页签可见时使用应用内横幅。';
    }
    return '当前浏览器不支持系统通知 API';
  }
  if (Notification.permission === 'denied') {
    return '本站通知权限已被拒绝。请在 Edge 地址栏左侧「锁/信息」图标 → 此网站的权限 → 通知 → 允许。';
  }
  return null;
}

/** 首次点击时申请浏览器通知权限，横幅才能弹出 */
export async function requestWebBannerPermission(): Promise<void> {
  if (!canUseBanner()) return;
  if (Notification.permission !== 'default') return;
  try {
    await Notification.requestPermission();
  } catch {
    // ignore
  }
}

function closeBanner(): void {
  try {
    lastBanner?.close();
  } catch {
    // ignore
  }
  lastBanner = null;
}

function resolveSenderName(ctx: IMTaskContext | undefined, conv: MockConversation | undefined): string {
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

function openConversation(taskID?: string): void {
  if (typeof window !== 'undefined') {
    try {
      window.focus();
    } catch {
      // ignore
    }
  }
  const id = taskID?.trim();
  if (!id) return;
  router.push({ pathname: '/chat/[id]', params: { id } } as unknown as Href);
}

function showBanner(params: {
  title: string;
  body: string;
  icon?: string;
  taskID?: string;
}): void {
  if (!canUseBanner() || Notification.permission !== 'granted') return;
  closeBanner();
  try {
    const n = new Notification(params.title, {
      body: params.body,
      icon: params.icon || resolveNotifyIconUri() || undefined,
      tag: BANNER_TAG,
    });
    n.onclick = () => {
      openConversation(params.taskID);
      n.close();
      if (lastBanner === n) lastBanner = null;
    };
    n.onclose = () => {
      if (lastBanner === n) lastBanner = null;
    };
    lastBanner = n;
  } catch {
    // 部分浏览器在未聚焦页禁止构造 Notification
  }
}

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

function matchConversationByIds(
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

function matchConversation(evt: Extract<IMGatewayEvent, { type: 'annotation_event' }>): MockConversation | undefined {
  const imConversationID = evt.task_context?.imConversationID;
  const taskID = evt.task_context?.taskID ?? evt.event?.taskID ?? '';
  return matchConversationByIds(imConversationID, taskID);
}

function shouldAlertIncoming(evt: IMGatewayEvent, conv: MockConversation | undefined): boolean {
  if (!isLoggedIn()) return false;
  if (evt.type !== 'annotation_event') return false;
  if (evt.event?.eventType !== 1) return false;

  const msg = evt.event?.message;
  if (!msg) return false;
  if (msg.direction !== 0) return false;

  const annotatorID = evt.event?.annotatorID;
  if (annotatorID && annotatorID !== getAgentId()) return false;

  if (conv && !isConversationOwnedAndActive(conv)) return false;

  return true;
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

function shouldAlertAiReview(
  evt: IMGatewayEvent,
  conv: MockConversation | undefined,
  ids: { taskID?: string; imConversationID?: string },
): boolean {
  if (!isLoggedIn()) return false;
  if (!isAiReviewGatewayEvent(evt)) return false;
  if (getRole() === 'supervisor') return false;

  const event =
    evt.type === 'ai_review_required' || evt.type === 'annotation_event'
      ? evt.event
      : undefined;
  const annotatorID = event?.annotatorID;
  if (annotatorID && annotatorID !== getAgentId()) return false;
  if (conv && !isConversationOwnedAndActive(conv)) return false;
  if (
    isConversationAdoptionHandled({
      taskID: ids.taskID,
      imConversationID: ids.imConversationID ?? conv?.imConversationID,
      adoptionID: event?.adoptionContext?.adoptionID,
    })
  ) {
    return false;
  }
  return true;
}

function presentIncomingAlert(params: {
  title: string;
  body: string;
  avatarUrl?: string;
  taskID?: string;
}): void {
  const icon = params.avatarUrl
    ? toAbsoluteUrl(params.avatarUrl)
    : resolveNotifyIconUri();

  // 页签隐藏：系统通知 + 标题闪烁（页面不可见，应用内横幅看不到）
  if (isTabHidden()) {
    startTitleFlash();
    playNotifySound();
    showBanner({
      title: params.title,
      body: params.body,
      icon,
      taskID: params.taskID,
    });
    return;
  }

  // 页签可见：始终出应用内顶部横幅
  playNotifySound();
  showIncomingBanner({
    title: params.title,
    body: params.body,
    avatarUrl: params.avatarUrl,
    taskID: params.taskID,
  });

  // 窗口失焦但页签仍开着：额外弹一次系统通知，方便从别的窗口切回
  if (isWindowUnfocused()) {
    showBanner({
      title: params.title,
      body: params.body,
      icon,
      taskID: params.taskID,
    });
  }
}

function handleGatewayEvent(evt: IMGatewayEvent): void {
  if (isAiReviewGatewayEvent(evt)) {
    const taskContext =
      evt.type === 'ai_review_required' || evt.type === 'annotation_event'
        ? evt.task_context
        : undefined;
    const event =
      evt.type === 'ai_review_required' || evt.type === 'annotation_event'
        ? evt.event
        : undefined;
    const imConversationID = taskContext?.imConversationID?.trim();
    const taskID = (taskContext?.taskID ?? event?.taskID)?.trim();
    const conv = matchConversationByIds(imConversationID, taskID);
    if (!shouldAlertAiReview(evt, conv, { taskID, imConversationID })) return;

    if (
      evt.type === 'ai_review_required' &&
      discardIfStaleAiReviewRequired(
        {
          lastTriggerMsgID: taskContext?.lastTriggerMsgID,
          convLastServerMsgID: conv?.lastMessage?.serverMsgID,
          taskID,
          imConversationID,
        },
        { stage: 'web_push_alert', eventID: event?.eventID ?? null },
      )
    ) {
      return;
    }

    if (isWebForeground() && isActiveChatConversation(imConversationID, taskID)) return;

    const key = event?.eventID?.trim() || event?.adoptionContext?.adoptionID?.trim() || '';
    if (key && consumeDedupeKey(`ai-review:${key}`)) return;

    const title = resolveSenderName(taskContext, conv);
    const body = resolveAiReviewBody(evt);
    const face =
      taskContext?.audiencePlatformFaceURL?.trim() ||
      conv?.audiencePlatformFaceURL?.trim();

    presentIncomingAlert({ title, body, avatarUrl: face, taskID });
    return;
  }

  const conv = evt.type === 'annotation_event' ? matchConversation(evt) : undefined;
  if (!shouldAlertIncoming(evt, conv)) return;

  const incoming = evt as Extract<IMGatewayEvent, { type: 'annotation_event' }>;
  const msg: IMServerMessage | undefined = incoming.event?.message;
  const imConversationID = incoming.task_context?.imConversationID?.trim();
  const taskID = (incoming.task_context?.taskID ?? incoming.event?.taskID)?.trim();

  // 正在看同一会话且窗口有焦点：消息已在列表里，不重复提醒；失焦仍通知
  if (isWebForeground() && isActiveChatConversation(imConversationID, taskID)) return;

  const key =
    incoming.event?.eventID?.trim() ||
    msg?.serverMsgID?.trim() ||
    '';
  if (key && consumeDedupeKey(key)) return;

  if (!msg) return;
  const title = resolveSenderName(incoming.task_context, conv);
  const body = previewFromServerMessage(msg);
  const face = incoming.task_context?.audiencePlatformFaceURL?.trim()
    || conv?.audiencePlatformFaceURL?.trim();

  presentIncomingAlert({ title, body, avatarUrl: face, taskID });
}

function restoreIfForeground(): void {
  if (isTabHidden()) return;
  stopTitleFlash();
  closeBanner();
}

function setupWebListeners(): () => void {
  if (typeof document === 'undefined' || typeof window === 'undefined') {
    return () => {};
  }

  document.addEventListener('visibilitychange', restoreIfForeground);
  window.addEventListener('focus', restoreIfForeground);
  window.addEventListener('pageshow', restoreIfForeground);

  const onInteract = () => {
    void unlockSound();
    void requestWebBannerPermission();
  };
  document.addEventListener('pointerdown', onInteract);
  document.addEventListener('click', onInteract);
  document.addEventListener('keydown', onInteract);

  return () => {
    document.removeEventListener('visibilitychange', restoreIfForeground);
    window.removeEventListener('focus', restoreIfForeground);
    window.removeEventListener('pageshow', restoreIfForeground);
    document.removeEventListener('pointerdown', onInteract);
    document.removeEventListener('click', onInteract);
    document.removeEventListener('keydown', onInteract);
  };
}

/** App 就绪后：若仍未授权，弹窗请用户开启桌面通知（页签隐藏时用） */
export function promptWebDesktopNotificationIfNeeded(): void {
  if (Platform.OS !== 'web') return;

  if (typeof Notification !== 'undefined' && Notification.permission === 'denied') {
    const blockReason = getWebNotificationBlockReason();
    appAlert('通知权限未开启', blockReason ?? '请在浏览器设置中允许本站通知', [{ text: '知道了' }]);
    return;
  }

  // HTTP 等非安全上下文：系统通知不可用，仅依赖应用内横幅
  if (!canUseBanner()) return;

  if (Notification.permission !== 'default') return;

  appAlert(
    '开启桌面通知',
    '有新消息时会在系统里弹出通知，方便你在别的窗口也能看到。\n\n提示：首次需在本页点击一次，提示音才会生效。',
    [
      { text: '暂不', style: 'cancel' },
      {
        text: '开启',
        onPress: () => {
          void requestWebBannerPermission();
          void unlockSound();
        },
      },
    ],
  );
}

/** 根布局常驻：Web 订阅网关新消息。原生 no-op。幂等。 */
export function initWebIncomingAlert(): () => void {
  if (Platform.OS !== 'web') return () => {};
  if (started) return disposeWebIncomingAlert;
  started = true;

  const chat = getChatService();
  const offGateway = chat.onGatewayEvent(handleGatewayEvent);
  const offDom = setupWebListeners();

  disposeFn = () => {
    offGateway();
    offDom();
    resetWebIncomingAlertUi();
    disposeFn = null;
    started = false;
  };

  return disposeWebIncomingAlert;
}

export function disposeWebIncomingAlert(): void {
  disposeFn?.();
}

/** 登出 / 回到页签：停闪烁、关横幅、还原标题。网关监听由根布局持有。 */
export function resetWebIncomingAlertUi(): void {
  stopTitleFlash();
  closeBanner();
  lastSoundAt = 0;
  seenKeys.clear();
  if (audioEl) {
    try {
      audioEl.pause();
      audioEl.currentTime = 0;
    } catch {
      // ignore
    }
  }
}
