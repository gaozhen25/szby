// Android 原生 heads-up 通知（高优先级渠道 + new_msg.wav 铃声）
import { NativeModules, Platform } from 'react-native';

type IncomingNotifyNative = {
  ensureChannels?: () => void;
  openChannelSettings?: () => void;
  showNotification: (
    title: string,
    body: string,
    extras: { taskID?: string; avatarUrl?: string } | null,
  ) => void;
};

const Native: IncomingNotifyNative | null =
  Platform.OS === 'android' ? (NativeModules.IncomingNotify as IncomingNotifyNative) : null;

export function isNativeIncomingNotifyAvailable(): boolean {
  return Boolean(Native?.showNotification);
}

/** 抢先创建高优先级渠道（含 new_msg 铃声） */
export function ensureNativeIncomingChannels(): void {
  if (!Native?.ensureChannels) return;
  try {
    Native.ensureChannels();
  } catch (e) {
    console.warn('[Notify] ensure native channels failed', e);
  }
}

export function openNativeIncomingChannelSettings(): void {
  if (!Native?.openChannelSettings) return;
  try {
    Native.openChannelSettings();
  } catch (e) {
    console.warn('[Notify] open channel settings failed', e);
  }
}

/** PRIORITY_MAX + 高优先级渠道；小米/OPPO/vivo 才能弹横幅并播自定义铃声 */
export function showNativeIncomingNotification(params: {
  title: string;
  body: string;
  taskID: string;
  avatarUrl?: string;
}): boolean {
  if (!Native?.showNotification) return false;
  try {
    Native.showNotification(params.title, params.body, {
      taskID: params.taskID || undefined,
      avatarUrl: params.avatarUrl?.trim() || undefined,
    });
    return true;
  } catch (e) {
    console.warn('[Notify] native incoming notification failed', e);
    return false;
  }
}
