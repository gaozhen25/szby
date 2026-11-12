import { useEffect } from 'react';
import { Flex, Spin, Typography } from 'antd';
import { router, usePathname } from 'expo-router';
import { isLoggedIn } from '@/core/auth';
import { waitForAuthBootstrap } from '@/core/auth-flow';
import { APP_NAME } from '@/lib/api-host';
import { webPageBg, webType } from '@/ui/web/theme';

export default function IndexPage() {
  const pathname = usePathname() ?? '';

  useEffect(() => {
    if (pathname.includes('/login') || pathname.includes('/register')) return;
    if (pathname && pathname !== '/' && pathname !== '/index') return;
    let alive = true;
    void (async () => {
      await waitForAuthBootstrap();
      if (!alive) return;
      if (isLoggedIn()) router.replace('/(tabs)/chat');
      else router.replace('/login');
    })();
    return () => {
      alive = false;
    };
  }, [pathname]);

  return (
    <Flex
      vertical
      align="center"
      justify="center"
      gap={16}
      style={{ minHeight: '100vh', height: '100%', background: webPageBg.index }}
    >
      <Typography.Title level={2} style={webType.authTitle}>
        {APP_NAME}
      </Typography.Title>
      <Spin />
    </Flex>
  );
}
