import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Animated,
  Dimensions,
  Keyboard,
  Platform,
  type KeyboardEvent,
} from 'react-native';

/**
 * Android：键盘遮挡屏幕底边的像素数。
 * 必须用 screen 高度与 screenY（屏幕绝对坐标），不能用 window.height：
 * adjustResize 时 window 已收缩，window 底边 ≈ keyboard 顶边，会算出 ≈0 导致输入框被挡。
 */
function resolveAndroidKeyboardLift(e: KeyboardEvent): number {
  const end = e.endCoordinates;
  if (!end) return 0;

  const keyboardH = Math.max(0, end.height ?? 0);
  if (typeof end.screenY === 'number' && Number.isFinite(end.screenY)) {
    const screenH = Dimensions.get('screen').height;
    const overlap = Math.max(0, screenH - end.screenY);
    if (overlap > 0) return overlap;
  }

  return keyboardH;
}

function liftFromMetrics(): number {
  const metrics = Keyboard.metrics?.();
  if (!metrics) return 0;
  const height = Math.max(0, metrics.height ?? 0);
  if (typeof metrics.screenY === 'number' && Number.isFinite(metrics.screenY)) {
    const screenH = Dimensions.get('screen').height;
    const overlap = Math.max(0, screenH - metrics.screenY);
    if (overlap > 0) return overlap;
  }
  return height;
}

function resolveKeyboardLift(e: KeyboardEvent): number {
  const end = e.endCoordinates;
  if (!end) return 0;

  if (Platform.OS === 'android') {
    return resolveAndroidKeyboardLift(e);
  }

  return Math.max(0, end.height ?? 0);
}

/**
 * 键盘跟随：
 * - Android adjustNothing + 底部垫高（仅抬高输入区，导航栏不动）
 * - iOS keyboardWillChangeFrame 跟随高度变化
 */
export function useKeyboardOffset(opts: { onKeyboardShow?: () => void } = {}) {
  const keyboardOffset = useRef(new Animated.Value(0)).current;
  const [keyboardVisible, setKeyboardVisible] = useState(false);
  const lastLiftRef = useRef(0);
  const keyboardOpenRef = useRef(false);
  const onKeyboardShowRef = useRef(opts.onKeyboardShow);
  onKeyboardShowRef.current = opts.onKeyboardShow;

  const applyLift = useCallback(
    (lift: number, duration: number, notifyDelay: number) => {
      lastLiftRef.current = lift;
      setKeyboardVisible(lift > 0);
      if (duration <= 0) {
        keyboardOffset.setValue(lift);
        if (lift > 0) {
          requestAnimationFrame(() => {
            onKeyboardShowRef.current?.();
            if (notifyDelay > 0) setTimeout(() => onKeyboardShowRef.current?.(), notifyDelay);
          });
        }
        return;
      }
      Animated.timing(keyboardOffset, {
        toValue: lift,
        duration,
        useNativeDriver: false,
      }).start(({ finished }) => {
        if (finished && lift > 0) {
          requestAnimationFrame(() => {
            onKeyboardShowRef.current?.();
            if (notifyDelay > 0) setTimeout(() => onKeyboardShowRef.current?.(), notifyDelay);
          });
        }
      });
    },
    [keyboardOffset],
  );

  const syncLiftFromKeyboard = useCallback(
    (e: KeyboardEvent, instant: boolean) => {
      keyboardOpenRef.current = true;
      const lift = resolveKeyboardLift(e);
      const duration = instant
        ? 0
        : Platform.OS === 'ios'
          ? (e.duration ?? 250)
          : 100;
      applyLift(lift, duration, Platform.OS === 'ios' ? 280 : 200);
    },
    [applyLift],
  );

  /** WebView 聚焦后键盘事件可能延迟，补一次同步 */
  const nudgeKeyboardLift = useCallback(() => {
    if (Platform.OS !== 'android') return;

    const applyFromMetrics = () => {
      const lift = liftFromMetrics();
      if (lift > 0 && Math.abs(lift - lastLiftRef.current) >= 1) {
        applyLift(lift, 0, 200);
        return true;
      }
      return false;
    };

    if (applyFromMetrics()) return;

    for (const delay of [80, 160, 280]) {
      setTimeout(applyFromMetrics, delay);
    }
  }, [applyLift]);

  useEffect(() => {
    if (Platform.OS === 'web') return;

    const onHide = (e: KeyboardEvent) => {
      keyboardOpenRef.current = false;
      const duration = Platform.OS === 'ios' ? (e.duration ?? 250) : 100;
      applyLift(0, duration, 0);
    };

    const onShowFrame = (e: KeyboardEvent) => syncLiftFromKeyboard(e, false);
    const onChangeFrame = (e: KeyboardEvent) => syncLiftFromKeyboard(e, true);

    const frameEvt =
      Platform.OS === 'ios' ? 'keyboardWillChangeFrame' : 'keyboardDidShow';
    const hideEvt = Platform.OS === 'ios' ? 'keyboardWillHide' : 'keyboardDidHide';

    const subs = [
      Keyboard.addListener(frameEvt, onShowFrame),
      Keyboard.addListener(hideEvt, onHide),
    ];

    if (Platform.OS === 'android') {
      subs.push(Keyboard.addListener('keyboardDidChangeFrame', onChangeFrame));
    }

    return () => {
      for (const sub of subs) sub.remove();
    };
  }, [applyLift, syncLiftFromKeyboard]);

  return { keyboardOffset, keyboardVisible, nudgeKeyboardLift };
}
