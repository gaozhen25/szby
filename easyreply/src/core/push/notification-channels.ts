// ============================================================
// Android 通知渠道：HIGH，避免被收进「不重要/静默」
// ============================================================
import { Platform } from 'react-native';
import * as Notifications from 'expo-notifications';

/** 渠道 id 一旦创建，sound 不可改，换铃声必须换 id */
export const INCOMING_CHANNEL_ID = 'qinghui_incoming_message_v2';
/** Android res/raw 文件名（无后缀）；与原生 IncomingNotifyChannels 一致 */
export const INCOMING_SOUND_ANDROID = 'new_msg';
export const INCOMING_SOUND_IOS = 'new_msg.wav';

let channelsReady = false;

export async function ensureIncomingMessageNotificationChannel(): Promise<void> {
  if (Platform.OS === 'web') return;

  try {
    const cur = await Notifications.getPermissionsAsync();
    if (!cur.granted) {
      await Notifications.requestPermissionsAsync({
        ios: { allowAlert: true, allowBadge: true, allowSound: true },
      });
    }
  } catch {
    // ignore
  }

  if (Platform.OS !== 'android' || channelsReady) return;

  try {
    await Notifications.setNotificationChannelAsync(INCOMING_CHANNEL_ID, {
      name: '新消息',
      description: '收到客户消息时弹出横幅并播放提示音',
      importance: Notifications.AndroidImportance.MAX,
      vibrationPattern: [0, 220, 90, 220],
      enableVibrate: true,
      enableLights: true,
      lockscreenVisibility: Notifications.AndroidNotificationVisibility.PUBLIC,
      showBadge: true,
      sound: INCOMING_SOUND_ANDROID,
      audioAttributes: {
        usage: Notifications.AndroidAudioUsage.NOTIFICATION,
        contentType: Notifications.AndroidAudioContentType.SONIFICATION,
        flags: {
          enforceAudibility: true,
          requestHardwareAudioVideoSynchronization: false,
        },
      },
    });
    channelsReady = true;
  } catch (e) {
    console.warn('[Notify] create incoming channel failed', e);
  }
}
