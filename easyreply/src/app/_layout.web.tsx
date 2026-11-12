import { lazy, Suspense, useEffect, type ReactNode } from 'react';
import { ErrorBoundary as ExpoRouterErrorBoundary } from 'expo-router';

import { wrapAppErrorBoundary, wrapRoot } from '@/core/sentry';
import { logBoundaryError } from '@/core/logging';
import { AppAlertHost } from '@/components/UI/AppAlertHost';
import { IncomingBannerHost } from '@/components/UI/IncomingBannerHost';
import { ToastHost } from '@/components/UI/ToastHost';
import { WebPhoneShell } from '@/components/UI/WebPhoneShell';
import { AppRootLayout } from '@/features/app/AppRootLayout';
import { loadChunkWithRecovery, recoverIfStaleBuild } from '@/lib/web-chunk-recovery';
import { useIsDesktopWeb } from '@/lib/web-desktop';
import { WebFullscreenLoader } from '@/ui/web/WebFullscreenLoader';

const SentryRoutedErrorBoundary = wrapAppErrorBoundary(ExpoRouterErrorBoundary);

const LazyDesktopWebChrome = lazy(
  loadChunkWithRecovery(() =>
    import('@/ui/web/desktop-shell').then((m) => ({ default: m.DesktopWebChrome })),
  ),
);
const LazyDesktopWebHosts = lazy(
  loadChunkWithRecovery(() =>
    import('@/ui/web/desktop-shell').then((m) => ({ default: m.DesktopWebHosts })),
  ),
);

function DesktopWebWrap({ children }: { children: ReactNode }) {
  return (
    <Suspense fallback={<WebFullscreenLoader />}>
      <LazyDesktopWebChrome>{children}</LazyDesktopWebChrome>
    </Suspense>
  );
}

function DesktopWebHostsLazy() {
  return (
    <Suspense fallback={null}>
      <LazyDesktopWebHosts />
    </Suspense>
  );
}

function RootLayout() {
  const isDesktop = useIsDesktopWeb();

  if (!isDesktop) {
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

  return (
    <AppRootLayout
      wrap={(content) => <DesktopWebWrap>{content}</DesktopWebWrap>}
      hosts={<DesktopWebHostsLazy />}
    />
  );
}

export default typeof wrapRoot === 'function' ? wrapRoot(RootLayout) : RootLayout;

export function ErrorBoundary(props: { error: Error; retry: () => Promise<void> }) {
  useEffect(() => {
    logBoundaryError(props.error);
    // 渲染期崩溃也可能是「页面跑的还是旧构建、服务器已经发了新版」造成的。
    // 不按错误文案猜（以前匹配 reading 'Title' 只能盖住标注员页那一种），
    // 而是去比对服务器构建版本：确认发过版才刷新一次，其余情况原样展示错误界面。
    void recoverIfStaleBuild();
  }, [props.error]);
  return <SentryRoutedErrorBoundary {...props} />;
}

export const unstable_settings = { initialRouteName: 'index' };
