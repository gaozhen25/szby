import { lazy, Suspense, type ComponentType, type LazyExoticComponent } from 'react';

import { loadChunkWithRecovery } from '@/lib/web-chunk-recovery';
import { useIsDesktopWeb } from '@/lib/web-desktop';
import { WebFullscreenLoader } from '@/ui/web/WebFullscreenLoader';

function WebRouteFallback() {
  return <WebFullscreenLoader />;
}

/**
 * Web 路由：窄屏用手机端页面，桌面页按路由懒加载。
 *
 * Native 必须静态传入：`import Native from './foo.tsx'`。
 * 显式 `.tsx` 以免解析回 `.web.tsx`；不能写成 `import('./foo.tsx')`，
 * 否则 Metro 热更新后模块号失效，报 Requiring unknown module。
 */
export function webRoute<P extends object>(
  loadWeb: () => Promise<{ default: ComponentType<P> }>,
  Native: ComponentType<P>,
): ComponentType<P> {
  const LazyWeb: LazyExoticComponent<ComponentType<P>> = lazy(loadChunkWithRecovery(loadWeb));

  function AdaptiveRoute(props: P) {
    const isDesktop = useIsDesktopWeb();
    if (!isDesktop) {
      return <Native {...props} />;
    }
    return (
      <Suspense fallback={<WebRouteFallback />}>
        <LazyWeb {...props} />
      </Suspense>
    );
  }
  return AdaptiveRoute;
}
