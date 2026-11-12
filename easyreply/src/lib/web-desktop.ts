import { useEffect, useState } from 'react';
import { useWindowDimensions } from 'react-native';

const DEFAULT_WEB_DESKTOP_MIN_WIDTH = 768;

function parseWebDesktopMinWidth(raw: string | undefined): number {
  const n = Number.parseInt(raw?.trim() ?? '', 10);
  return Number.isFinite(n) && n > 0 ? n : DEFAULT_WEB_DESKTOP_MIN_WIDTH;
}

/** 浏览器宽度达到此值时使用桌面 Web UI（antd 三栏工作台），见 EXPO_PUBLIC_WEB_DESKTOP_MIN_WIDTH */
export const WEB_DESKTOP_MIN_WIDTH = parseWebDesktopMinWidth(
  process.env.EXPO_PUBLIC_WEB_DESKTOP_MIN_WIDTH,
);

export function getIsDesktopWeb(width: number): boolean {
  return width >= WEB_DESKTOP_MIN_WIDTH;
}

function readInitialDesktopWeb(): boolean {
  if (typeof window === 'undefined') return true;
  return getIsDesktopWeb(window.innerWidth);
}

/** Web 端：按视口宽度区分桌面工作台与手机端 UI */
export function useIsDesktopWeb(): boolean {
  const { width } = useWindowDimensions();
  const [isDesktop, setIsDesktop] = useState(readInitialDesktopWeb);

  useEffect(() => {
    // RN-web 首帧偶发 width=0，当成窄屏会整树切到手机端页面再切回来
    if (width <= 0) return;
    setIsDesktop(getIsDesktopWeb(width));
  }, [width]);

  return isDesktop;
}
