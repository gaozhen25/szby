// ============================================================
// 推送通知点击 / 透传消息路由
// ============================================================
import { router } from 'expo-router';

import type { JPushNotificationEvent } from './jpush';

function getNotificationEventType(raw: unknown): string | null {
  if (!raw || typeof raw !== 'object') return null;
  const v = (raw as Record<string, unknown>).notificationEventType;
  return typeof v === 'string' ? v : null;
}

function pickString(extras: Record<string, unknown>, keys: string[]): string | null {
  for (const key of keys) {
    const v = extras[key];
    if (typeof v === 'string' && v.trim()) return v.trim();
  }
  return null;
}

/** 点击系统通知 / 本地推送后跳转会话 */
export function openChatFromPushExtras(extras: Record<string, unknown> | null): void {
  const conversationId = extras
    ? pickString(extras, [
        'conversationId',
        'conversation_id',
        'taskID',
        'taskId',
        'chatId',
        'chat_id',
      ])
    : null;

  if (conversationId) {
    router.push(`/chat/${conversationId}`);
    return;
  }

  router.push('/(tabs)/chat');
}

/** 处理通知到达 / 点击 */
export function handleJPushNotification(evt: JPushNotificationEvent): void {
  const eventType = getNotificationEventType(evt.raw);
  if (eventType && eventType !== 'notificationOpened') {
    return;
  }

  openChatFromPushExtras(evt.extras);
}

/** 处理透传消息（可用于 IM 静默同步，后续接 WS 补拉） */
export function handleJPushCustomMessage(evt: JPushNotificationEvent): void {
  if (__DEV__) {
    console.log('[JPush] custom message', evt.extras ?? evt.raw);
  }
}
