import { useEffect } from 'react';
import { ErrorBoundary as ExpoRouterErrorBoundary } from 'expo-router';

import { wrapAppErrorBoundary } from '@/core/sentry';
import { logBoundaryError } from '@/core/logging';
import { AppAlertHost } from '@/components/UI/AppAlertHost';
import { IncomingBannerHost } from '@/components/UI/IncomingBannerHost';
import { ToastHost } from '@/components/UI/ToastHost';
import { WebPhoneShell } from '@/components/UI/WebPhoneShell';
import { AppRootLayout, wrapRoot } from '@/features/app/AppRootLayout';

function RootLayout() {
  return (
    <AppRootLayout
      wrap={(content) => <WebPhoneShell>{content}</WebPhoneShell>}
      hosts={
        <>
          <AppAlertHost />
          <ToastHost />
          <IncomingBannerHost />
        </>
      }
    />
  );
}

// 导出 ErrorBoundary：本地落盘 + Sentry wrap（页面 render 崩溃）
const SentryRoutedErrorBoundary = wrapAppErrorBoundary(ExpoRouterErrorBoundary);

export function ErrorBoundary(props: { error: Error; retry: () => Promise<void> }) {
  useEffect(() => {
    logBoundaryError(props.error);
  }, [props.error]);
  return <SentryRoutedErrorBoundary {...props} />;
}

export const unstable_settings = { initialRouteName: 'index' };

// Fast Refresh 重载中间态时 named import 可能短暂不是函数，直接透传根组件避免白屏
export default typeof wrapRoot === 'function' ? wrapRoot(RootLayout) : RootLayout;
