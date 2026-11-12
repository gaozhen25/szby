import { Platform } from 'react-native';

/**
 * Android edge-to-edge 下部分机型 safe-area bottom 会报 0，
 * 导致 TabBar / 输入栏被系统导航条（三键/手势条）挡住。
 * 三键导航条常见高度约 48dp；有真实 inset 时优先用系统值。
 */
const ANDROID_NAV_FALLBACK = 48;

export function resolveBottomInset(rawBottom: number): number {
  if (Platform.OS === 'android' && rawBottom <= 0) {
    return ANDROID_NAV_FALLBACK;
  }
  return Math.max(0, rawBottom);
}
