import { lazy, Suspense, type ReactNode } from 'react';

import { useIsDesktopWeb } from '@/lib/web-desktop';
import { WebFullscreenLoader } from '@/ui/web/WebFullscreenLoader';
import { TabsLayoutShared } from '@/features/app/TabsLayoutShared';

const LazyAppShell = lazy(() =>
  import('@/ui/web/desktop-shell').then((m) => ({ default: m.AppShell })),
);

function DesktopTabsLayout({ children }: { children: ReactNode }) {
  return (
    <Suspense fallback={<WebFullscreenLoader />}>
      <LazyAppShell>{children}</LazyAppShell>
    </Suspense>
  );
}

/** Web：桌面用侧栏 + 隐藏 TabBar；窄屏使用手机端底部 Tab */
export default function TabLayout() {
  const isDesktop = useIsDesktopWeb();
  const tabs = <TabsLayoutShared hideTabBar={isDesktop} />;

  if (isDesktop) {
    return <DesktopTabsLayout>{tabs}</DesktopTabsLayout>;
  }

  return tabs;
}
