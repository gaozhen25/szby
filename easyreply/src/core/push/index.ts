// ============================================================
// 推送模块启动入口
// ============================================================
import { Platform } from 'react-native';

import { registerPushToken } from '@/api';
import { isLoggedIn } from '@/core/auth';

import {
  handleJPushCustomMessage,
  handleJPushNotification,
} from './handlers';
import {
  getJPushRegistrationIdWithRetry,
  initJPushSdkOnce,
  isJPushConfigured,
  registerJPushEventListeners,
  requestJPushNotificationPermission,
} from './jpush';
import { resetIncomingMessageAlertUi } from './incoming-message-alert';
import {
  initLocalNotificationRuntime,
  registerLocalNotificationTapListener,
} from './local-notification';
import { ensureNativeIncomingChannels } from './native-incoming-notify';
import { ensureIncomingMessageNotificationChannel } from './notification-channels';

let didBootstrap = false;
let unregisterListeners: (() => void) | null = null;
let cachedRegistrationId: string | null = null;

/** 同步初始化 SDK（根布局顶层调用） */
export function initPushRuntime(): void {
  initJPushSdkOnce();
  initLocalNotificationRuntime();
  ensureNativeIncomingChannels();
}

/** 请求权限、注册监听（App 启动后调用一次） */
export async function bootstrapPush(): Promise<void> {
  if (Platform.OS === 'web') return;
  if (didBootstrap) return;
  didBootstrap = true;

  const unsubs: Array<() => void> = [registerLocalNotificationTapListener()];
  ensureNativeIncomingChannels();
  void ensureIncomingMessageNotificationChannel();

  if (isJPushConfigured()) {
    await requestJPushNotificationPermission();
    unsubs.push(
      registerJPushEventListeners({
        onNotification: handleJPushNotification,
        onCustomMessage: handleJPushCustomMessage,
      }),
    );
    if (isLoggedIn()) {
      await bindPushRegistrationId();
    }
  }

  unregisterListeners = () => {
    for (const fn of unsubs) fn();
  };
}

/** 登录成功后绑定 RegistrationID 到服务端 */
export async function bindPushRegistrationId(): Promise<string | null> {
  if (Platform.OS === 'web' || !isJPushConfigured()) return null;

  const regId = await getJPushRegistrationIdWithRetry();
  if (!regId) {
    console.warn('[JPush] registration id unavailable');
    return null;
  }

  if (cachedRegistrationId === regId) {
    return regId;
  }

  try {
    await registerPushToken({
      registrationId: regId,
      platform: Platform.OS as 'ios' | 'android',
    });
    cachedRegistrationId = regId;
    console.log('[JPush] registration id bound');
  } catch (e) {
    console.warn('[JPush] bind registration id failed', e);
  }

  return regId;
}

/** 登出时清理缓存 */
export function resetPushBindingCache(): void {
  cachedRegistrationId = null;
}

/** 销毁监听（一般不需要，登出时可调用） */
export function teardownPushListeners(): void {
  unregisterListeners?.();
  unregisterListeners = null;
  didBootstrap = false;
  resetPushBindingCache();
  resetIncomingMessageAlertUi();
}

export {
  initJPushSdkOnce,
  isJPushConfigured,
  resolveJPushProduction,
  sendJPushLocalNotification,
} from './jpush';

export {
  initIncomingMessageAlert,
  disposeIncomingMessageAlert,
  resetIncomingMessageAlertUi,
} from './incoming-message-alert';

export {
  initWebIncomingAlert,
  disposeWebIncomingAlert,
  resetWebIncomingAlertUi,
  requestWebBannerPermission,
  promptWebDesktopNotificationIfNeeded,
} from './web-incoming-alert';

export type { JPushNotificationEvent } from './jpush';
