// ============================================================
// 极光推送 SDK 封装（jpush-react-native）
// ============================================================
import { PermissionsAndroid, Platform } from 'react-native';

type JPushModule = {
  setLoggerEnable?: (enable: boolean) => void;
  init?: (params: { appKey: string; channel: string; production: boolean }) => void;
  getRegistrationID?: (cb: (result: unknown) => void) => void;
  isNotificationEnabled?: (cb: (enabled: unknown) => void) => void;
  addNotificationListener?: (cb: (payload: unknown) => void) => void;
  removeNotificationListener?: (cb: (payload: unknown) => void) => void;
  addReceiveCustomMsgListener?: (cb: (payload: unknown) => void) => void;
  removeReceiveCustomMsgListener?: (cb: (payload: unknown) => void) => void;
  addListener?: (event: string, cb: (payload: unknown) => void) => unknown;
  removeListener?: (event: string, cb: (payload: unknown) => void) => void;
  addEventListener?: (event: string, cb: (payload: unknown) => void) => unknown;
  removeEventListener?: (event: string, cb: (payload: unknown) => void) => void;
  addLocalNotification?: (params: {
    messageID: string;
    title?: string;
    content: string;
    extras?: Record<string, string>;
  }) => void;
};

function getJPushModule(): JPushModule | null {
  if (Platform.OS === 'web') return null;
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const mod = require('jpush-react-native');
    return (mod?.default ?? mod) as JPushModule;
  } catch {
    return null;
  }
}

let didInitJPushSdk = false;

function coerceBoolEnv(v: unknown, fallback: boolean): boolean {
  if (typeof v !== 'string') return fallback;
  const s = v.trim().toLowerCase();
  if (s === 'true' || s === '1' || s === 'yes' || s === 'y') return true;
  if (s === 'false' || s === '0' || s === 'no' || s === 'n') return false;
  return fallback;
}

/** 按运行环境决定是否走极光生产通道 */
export function resolveJPushProduction(): boolean {
  const appEnv = process.env.EXPO_PUBLIC_APP_ENV?.trim() || 'production';
  if (appEnv === 'production') {
    return coerceBoolEnv(process.env.EXPO_PUBLIC_JPUSH_PRODUCTION, true);
  }
  return false;
}

export function isJPushConfigured(): boolean {
  return Boolean((process.env.EXPO_PUBLIC_JPUSH_APP_KEY ?? '').trim());
}

/**
 * JS 侧初始化极光 SDK（尽早调用，且只需一次）
 * 原生侧由 mx-jpush-expo 注入配置
 */
export function initJPushSdkOnce(): void {
  if (didInitJPushSdk) return;
  didInitJPushSdk = true;
  if (Platform.OS === 'web') return;

  const JPush = getJPushModule();
  if (!JPush?.init) {
    console.warn('[JPush] jpush-react-native not available (Expo Go / Web)');
    return;
  }

  const appKey = (process.env.EXPO_PUBLIC_JPUSH_APP_KEY ?? '').trim();
  const channel = (process.env.EXPO_PUBLIC_JPUSH_CHANNEL ?? 'developer-default').trim();
  const production = resolveJPushProduction();

  if (!appKey) {
    console.warn('[JPush] EXPO_PUBLIC_JPUSH_APP_KEY not set');
    return;
  }

  try {
    JPush.setLoggerEnable?.(__DEV__ === true);
    JPush.init({ appKey, channel, production });
    console.log(`[JPush] init ok · production=${production}`);
  } catch (e) {
    console.warn('[JPush] init failed', e);
  }
}

function normalizeRegistrationId(result: unknown): string | null {
  if (typeof result === 'string') {
    const v = result.trim();
    return v || null;
  }
  if (result && typeof result === 'object') {
    const rec = result as Record<string, unknown>;
    const v =
      rec.registerID ??
      rec.registrationID ??
      rec.registrationId ??
      rec.registerId;
    if (typeof v === 'string') {
      const s = v.trim();
      return s || null;
    }
  }
  return null;
}

export type JPushExtras = Record<string, unknown>;

export type JPushNotificationEvent = {
  raw: unknown;
  extras: JPushExtras | null;
};

export type JPushEventHandlers = {
  onNotification?: (evt: JPushNotificationEvent) => void;
  onCustomMessage?: (evt: JPushNotificationEvent) => void;
};

function normalizeExtras(extras: unknown): JPushExtras | null {
  if (!extras) return null;
  if (typeof extras === 'object') return extras as JPushExtras;
  if (typeof extras === 'string') {
    const s = extras.trim();
    if (!s) return null;
    try {
      const parsed = JSON.parse(s) as unknown;
      return parsed && typeof parsed === 'object' ? (parsed as JPushExtras) : null;
    } catch {
      return null;
    }
  }
  return null;
}

function extractExtrasFromPayload(payload: unknown): JPushExtras | null {
  if (!payload || typeof payload !== 'object') return null;
  const rec = payload as Record<string, unknown>;
  return (
    normalizeExtras(rec.extras) ??
    normalizeExtras(rec.extra) ??
    normalizeExtras(rec.extrasMap) ??
    null
  );
}

function safeCall(
  cb: ((evt: JPushNotificationEvent) => void) | undefined,
  raw: unknown,
): void {
  if (!cb) return;
  try {
    cb({ raw, extras: extractExtrasFromPayload(raw) });
  } catch {
    // ignore handler errors
  }
}

export function registerJPushEventListeners(
  handlers: JPushEventHandlers,
): () => void {
  if (Platform.OS === 'web') return () => {};
  const JPush = getJPushModule();
  if (!JPush) return () => {};

  const unsubs: Array<() => void> = [];
  const onNotif = (payload: unknown) => safeCall(handlers.onNotification, payload);
  const onCustom = (payload: unknown) => safeCall(handlers.onCustomMessage, payload);

  if (JPush.addNotificationListener) {
    JPush.addNotificationListener(onNotif);
    const rm = JPush.removeNotificationListener;
    unsubs.push(() => {
      try {
        rm?.(onNotif);
      } catch {
        // ignore
      }
    });
  }

  if (JPush.addReceiveCustomMsgListener) {
    JPush.addReceiveCustomMsgListener(onCustom);
    const rm = JPush.removeReceiveCustomMsgListener;
    unsubs.push(() => {
      try {
        rm?.(onCustom);
      } catch {
        // ignore
      }
    });
  }

  const add = JPush.addListener ?? JPush.addEventListener;
  const remove = JPush.removeListener ?? JPush.removeEventListener;
  if (add && remove && unsubs.length === 0) {
    for (const [event, cb] of [
      ['receiveNotification', onNotif],
      ['receiveCustomMsg', onCustom],
    ] as const) {
      try {
        add(event, cb);
        unsubs.push(() => {
          try {
            remove(event, cb);
          } catch {
            // ignore
          }
        });
      } catch {
        // ignore
      }
    }
  }

  return () => {
    for (const fn of unsubs) fn();
  };
}

export async function getJPushRegistrationId(): Promise<string | null> {
  const JPush = getJPushModule();
  const getter = JPush?.getRegistrationID;
  if (!getter) return null;

  return new Promise((resolve) => {
    try {
      getter((result) => resolve(normalizeRegistrationId(result)));
    } catch {
      resolve(null);
    }
  });
}

export async function getJPushRegistrationIdWithRetry(
  maxAttempts = 6,
  delayMs = 1000,
): Promise<string | null> {
  for (let i = 0; i < maxAttempts; i += 1) {
    const id = await getJPushRegistrationId();
    if (id) return id;
    await new Promise((r) => setTimeout(r, delayMs));
  }
  return null;
}

async function requestAndroidPostNotificationsPermission(): Promise<void> {
  if (Platform.OS !== 'android') return;
  const apiLevel = typeof Platform.Version === 'number' ? Platform.Version : null;
  if (apiLevel == null || apiLevel < 33) return;

  const permission = PermissionsAndroid.PERMISSIONS.POST_NOTIFICATIONS;
  if (!permission) return;

  try {
    const granted = await PermissionsAndroid.check(permission);
    if (granted) return;
    await PermissionsAndroid.request(permission);
  } catch {
    // ignore
  }
}

async function requestIosNotificationPermissionViaJPush(): Promise<void> {
  if (Platform.OS !== 'ios') return;
  const fn = getJPushModule()?.isNotificationEnabled;
  if (!fn) return;

  await new Promise<void>((resolve) => {
    try {
      fn(() => resolve());
    } catch {
      resolve();
    }
  });
}

export async function requestJPushNotificationPermission(): Promise<void> {
  if (Platform.OS === 'web') return;
  await Promise.all([
    requestIosNotificationPermissionViaJPush(),
    requestAndroidPostNotificationsPermission(),
  ]);
}

export function sendJPushLocalNotification(params: {
  title?: string;
  content: string;
  extras?: Record<string, string>;
}): void {
  if (Platform.OS === 'web') return;
  const JPush = getJPushModule();
  if (!JPush?.addLocalNotification) return;

  const messageID = String(Math.max(1, Math.floor(Date.now() % 2_147_483_647)));
  try {
    JPush.addLocalNotification({
      messageID,
      title: params.title,
      content: params.content,
      extras: params.extras,
    });
  } catch {
    // ignore
  }
}

export function resetJPushSdkStateForTests(): void {
  didInitJPushSdk = false;
}
