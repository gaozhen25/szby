import { useEffect, type ReactNode } from 'react';
import { App as AntdApp, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { APP_OVERLAY_HOST_ID } from '@/lib/app-overlay-host';
import { qinghuiAntdTheme, webModalCloseStyle } from '@/ui/web/theme';
import { bindOverlayHost, ensureWebDesktopCss } from '@/ui/web/setup-viewport';

let antdConsolePatched = false;

/** Expo LogBox 会把 antd 的 console.error 弃用提示做成全屏红屏 */
function silenceAntdDeprecationOverlay(): void {
  if (antdConsolePatched || typeof console === 'undefined') return;
  antdConsolePatched = true;
  const origError = console.error.bind(console);
  const origWarn = console.warn.bind(console);
  const isAntdDeprecation = (args: unknown[]) =>
    args.some((arg) => typeof arg === 'string' && arg.includes('[antd:'));
  console.error = (...args: unknown[]) => {
    if (isAntdDeprecation(args)) return;
    origError(...args);
  };
  console.warn = (...args: unknown[]) => {
    if (isAntdDeprecation(args)) return;
    origWarn(...args);
  };
}

export function AntdRoot({ children }: { children: ReactNode }) {
  silenceAntdDeprecationOverlay();
  ensureWebDesktopCss();
  useEffect(() => {
    // Fast Refresh 会先跑旧 effect cleanup，再跑新实例。cleanup 里若卸掉 CSS，
    // 主栏会变成空白，必须手动刷新；所以卸载时只收 overlay，样式留着并在此补写。
    ensureWebDesktopCss();
    const el = document.createElement('div');
    el.id = APP_OVERLAY_HOST_ID;
    el.style.position = 'fixed';
    el.style.inset = '0';
    el.style.pointerEvents = 'none';
    el.style.zIndex = '4000';
    document.body.appendChild(el);
    bindOverlayHost(el);
    return () => {
      el.remove();
      bindOverlayHost(null);
    };
  }, []);

  return (
    <ConfigProvider
      locale={zhCN}
      theme={qinghuiAntdTheme}
      warning={{ strict: false }}
      modal={{
        styles: { close: webModalCloseStyle },
      }}
    >
      <AntdApp
        style={{ height: '100%' }}
        message={{ top: 64, maxCount: 3 }}
        notification={{ placement: 'topRight' }}
      >
        {children}
      </AntdApp>
    </ConfigProvider>
  );
}
