// ============================================================
// 跨端弹窗：原生走 Alert.alert，Web 走全局 Modal Host
// listeners 挂 globalThis，避免静态导出分包导致「发/订」不是同一份 Set
// ============================================================
import { Alert, Platform } from 'react-native';

export type AppAlertButton = {
  text?: string;
  style?: 'default' | 'cancel' | 'destructive';
  onPress?: () => void;
  /** Web：关闭弹窗时跳过进出场动画（如退出登录后立刻跳转） */
  closeWithoutAnimation?: boolean;
};

export type AppAlertPayload = {
  title: string;
  message?: string;
  buttons: AppAlertButton[];
};

type Listener = (payload: AppAlertPayload | null) => void;

const GLOBAL_KEY = '__qinghui_app_alert_listeners__';

function getListeners(): Set<Listener> {
  const g = globalThis as typeof globalThis & { [GLOBAL_KEY]?: Set<Listener> };
  if (!g[GLOBAL_KEY]) g[GLOBAL_KEY] = new Set();
  return g[GLOBAL_KEY]!;
}

export function subscribeAppAlert(listener: Listener): () => void {
  const listeners = getListeners();
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function emitAppAlert(payload: AppAlertPayload | null) {
  getListeners().forEach((fn) => fn(payload));
}

/** 关闭当前 Web 弹窗（AppAlertHost 调用） */
export function dismissAppAlert() {
  emitAppAlert(null);
}

/**
 * 与 `Alert.alert` 签名兼容的跨端弹窗。
 * - iOS / Android：原生 Alert
 * - Web：由根布局 `AppAlertHost` 渲染遮罩层
 */
export function appAlert(
  title: string,
  message?: string,
  buttons?: AppAlertButton[],
): void {
  const resolved: AppAlertButton[] =
    buttons && buttons.length > 0
      ? buttons
      : [{ text: '知道了', style: 'default' }];

  if (Platform.OS !== 'web') {
    Alert.alert(title, message, resolved);
    return;
  }

  emitAppAlert({ title, message, buttons: resolved });
}
