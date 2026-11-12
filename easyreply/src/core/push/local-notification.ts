// ============================================================
// 后台本地系统通知（App 进程还在、已离开前台）
// ============================================================
import { AppState, Platform } from 'react-native';
import * as Notifications from 'expo-notifications';

import { isJPushConfigured, sendJPushLocalNotification } from './jpush';
import { openChatFromPushExtras } from './handlers';
import {
  showNativeIncomingNotification,
} from './native-incoming-notify';
import {
  INCOMING_CHANNEL_ID,
  INCOMING_SOUND_IOS,
  ensureIncomingMessageNotificationChannel,
} from './notification-channels';

let didInit = false;
let tapSub: { remove: () => void } | null = null;

export function initLocalNotificationRuntime(): void {
  if (didInit || Platform.OS === 'web') return;
  didInit = true;

  Notifications.setNotificationHandler({
    handleNotification: async () => {
      const inForeground = AppState.currentState === 'active';
      return {
        shouldShowAlert: !inForeground,
        shouldShowBanner: !inForeground,
        shouldShowList: true,
        shouldPlaySound: !inForeground,
        shouldSetBadge: true,
        priority: Notifications.AndroidNotificationPriority.MAX,
      };
    },
  });
}

export function registerLocalNotificationTapListener(): () => void {
  if (Platform.OS === 'web') return () => {};
  tapSub?.remove();
  tapSub = Notifications.addNotificationResponseReceivedListener((response) => {
    const data = response.notification.request.content.data;
    openChatFromPushExtras(data && typeof data === 'object' ? (data as Record<string, unknown>) : null);
  });
  return () => {
    tapSub?.remove();
    tapSub = null;
  };
}

export function presentIncomingLocalNotification(params: {
  title: string;
  body: string;
  taskID: string;
  avatarUrl?: string;
}): void {
  if (Platform.OS === 'web') return;

  const displayTitle = params.title.trim() || '新消息';
  const displayBody = params.body.trim() || '您有一条新消息';
  const extras: Record<string, string> = {
    conversationId: params.taskID,
    taskID: params.taskID,
  };

  // Android：走原生模块（渠道绑 new_msg.wav，MIUI 才能出声）；expo 仅作兜底
  if (Platform.OS === 'android') {
    if (
      showNativeIncomingNotification({
        title: displayTitle,
        body: displayBody,
        taskID: params.taskID,
        avatarUrl: params.avatarUrl,
      })
    ) {
      return;
    }
  }

  void (async () => {
    try {
      await ensureIncomingMessageNotificationChannel();
      await Notifications.scheduleNotificationAsync({
        identifier: params.taskID ? `qh-msg-${params.taskID}` : undefined,
        content: {
          title: displayTitle,
          body: displayBody,
          sound: Platform.OS === 'ios' ? INCOMING_SOUND_IOS : true,
          priority: Notifications.AndroidNotificationPriority.MAX,
          interruptionLevel: 'timeSensitive',
          data: extras,
        },
        trigger: Platform.OS === 'android' ? { channelId: INCOMING_CHANNEL_ID } : null,
      });
    } catch (e) {
      console.warn('[Notify] expo local notification failed', e);
      if (Platform.OS === 'android' && isJPushConfigured()) {
        sendJPushLocalNotification({
          title: displayTitle,
          content: displayBody,
          extras,
        });
      }
    }
  })();
}
