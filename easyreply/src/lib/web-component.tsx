import {
  forwardRef,
  type ComponentType,
  type ForwardRefExoticComponent,
  type RefAttributes,
} from 'react';
import { useIsDesktopWeb } from '@/lib/web-desktop';

/**
 * Web 组件：窄屏用手机端实现，桌面用 Web 实现。
 *
 * Native 必须静态传入：`import { Foo } from './Foo.tsx'`。
 * 显式 `.tsx` 以免解析回 `.web.tsx`；不要动态 import，
 * Metro Web 热更新后模块号会失效（Requiring unknown module）。
 */
export function webComponent<P extends object>(
  Web: ComponentType<P>,
  Native: ComponentType<P>,
): ComponentType<P> {
  function AdaptiveComponent(props: P) {
    const isDesktop = useIsDesktopWeb();
    return isDesktop ? <Web {...props} /> : <Native {...props} />;
  }
  return AdaptiveComponent;
}

export function webComponentWithRef<P extends object, R>(
  Web: ForwardRefExoticComponent<P & RefAttributes<R>>,
  Native: ForwardRefExoticComponent<P & RefAttributes<R>>,
): ForwardRefExoticComponent<P & RefAttributes<R>> {
  const AdaptiveComponent = forwardRef<R, P>(function AdaptiveComponent(props, ref) {
    const isDesktop = useIsDesktopWeb();
    return isDesktop ? <Web {...(props as P)} ref={ref} /> : <Native {...(props as P)} ref={ref} />;
  });
  return AdaptiveComponent as ForwardRefExoticComponent<P & RefAttributes<R>>;
}
