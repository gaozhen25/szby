import type { ReactNode } from 'react';

import { IncomingBannerHost } from '@/components/UI/IncomingBannerHost';
import { AntdRoot } from '@/ui/web/AntdRoot';
import { WebAlertHost } from '@/ui/web/hosts/WebAlertHost';
import { WebProfileHost } from '@/ui/web/hosts/WebProfileHost';
import { WebToastHost } from '@/ui/web/hosts/WebToastHost';

/** 桌面 Web 壳层（antd + hosts），由 _layout.web 懒加载 */
export function DesktopWebChrome({ children }: { children: ReactNode }) {
  return <AntdRoot>{children}</AntdRoot>;
}

export function DesktopWebHosts() {
  return (
    <>
      <WebAlertHost />
      <WebToastHost />
      <IncomingBannerHost />
      <WebProfileHost />
    </>
  );
}
