import { Alert, Button, Empty, Flex, Result } from 'antd';
import { isProductionEnv } from '@/lib/api-host';
import { PageFrame } from '@/ui/web/PageFrame';
import type { ReactNode } from 'react';

export function WebUnderDevelopment({
  title,
  subtitle,
  withShell = false,
  showBack = false,
}: {
  title: string;
  subtitle?: string;
  withShell?: boolean;
  showBack?: boolean;
}) {
  return (
    <PageFrame title={title} withShell={withShell} showBack={showBack}>
      <Flex align="center" justify="center" style={{ height: '100%' }}>
        <Result status="info" title="功能开发中" subTitle={subtitle || '敬请期待'} />
      </Flex>
    </PageFrame>
  );
}

export function maybeDevOnly(title: string, subtitle: string, content: ReactNode, opts?: { withShell?: boolean; showBack?: boolean }) {
  if (isProductionEnv) {
    return (
      <WebUnderDevelopment
        title={title}
        subtitle={subtitle}
        withShell={opts?.withShell}
        showBack={opts?.showBack}
      />
    );
  }
  return content;
}

export function EmptyHint({ text }: { text: string }) {
  return (
    <Flex align="center" justify="center" style={{ height: '100%' }}>
      <Empty description={text} />
    </Flex>
  );
}

export function ErrorHint({ text, onRetry }: { text: string; onRetry?: () => void }) {
  return <Alert type="error" title={text} showIcon action={onRetry ? <Button onClick={onRetry}>重试</Button> : null} />;
}
