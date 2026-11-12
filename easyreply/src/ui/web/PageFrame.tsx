import { Button, Flex, Typography } from 'antd';
import { ArrowLeftOutlined } from '@/ui/web/antd-icons';
import { router } from 'expo-router';
import type { ReactNode } from 'react';
import { AppShell } from '@/ui/web/AppShell';
import { webColor, webPageBg, webType } from '@/ui/web/theme';

export function PageFrame({
  title,
  subtitle,
  extra,
  children,
  showBack = true,
  withShell = true,
}: {
  title: string;
  subtitle?: string;
  extra?: ReactNode;
  children: ReactNode;
  showBack?: boolean;
  withShell?: boolean;
}) {
  const body = (
    <Flex vertical className="qh-page-frame" style={{ height: '100%', minHeight: 0, flex: 1 }}>
      <Flex
        align="center"
        gap={12}
        style={{
          padding: '10px 20px',
          borderBottom: `1px solid ${webColor.separator}`,
          background: webPageBg.pageHeader,
          flexShrink: 0,
        }}
      >
        {showBack ? (
          <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => router.back()} />
        ) : null}
        <Flex vertical style={{ flex: 1, minWidth: 0 }} gap={0}>
          <Typography.Title level={4} style={webType.pageTitle}>
            {title}
          </Typography.Title>
          {subtitle ? (
            <Typography.Text type="secondary" style={webType.pageSubtitle}>
              {subtitle}
            </Typography.Text>
          ) : null}
        </Flex>
        {extra}
      </Flex>
      <Flex vertical flex={1} style={{ minHeight: 0, overflow: 'hidden' }}>
        {children}
      </Flex>
    </Flex>
  );
  return withShell ? <AppShell>{body}</AppShell> : body;
}
