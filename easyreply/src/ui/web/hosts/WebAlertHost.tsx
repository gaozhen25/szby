import { Button, Modal, Typography } from 'antd';
import { CloseOutlined } from '@/ui/web/antd-icons';
import { useEffect, useState } from 'react';
import {
  dismissAppAlert,
  subscribeAppAlert,
  type AppAlertButton,
  type AppAlertPayload,
} from '@/lib/app-alert';
import { webModalCloseStyle, webType } from '@/ui/web/theme';

export function WebAlertHost() {
  const [payload, setPayload] = useState<AppAlertPayload | null>(null);
  const [skipMotion, setSkipMotion] = useState(false);

  useEffect(
    () =>
      subscribeAppAlert((next) => {
        if (next) setSkipMotion(false);
        setPayload(next);
      }),
    [],
  );

  const handlePress = (btn: AppAlertButton) => {
    if (btn.closeWithoutAnimation) setSkipMotion(true);
    dismissAppAlert();
    queueMicrotask(() => btn.onPress?.());
  };

  return (
    <Modal
      open={!!payload}
      title={payload?.title}
      maskClosable={false}
      closeIcon={<CloseOutlined />}
      onCancel={() => dismissAppAlert()}
      styles={{ title: webType.modalTitle, close: webModalCloseStyle }}
      zIndex={2000}
      transitionName={skipMotion ? '' : undefined}
      maskTransitionName={skipMotion ? '' : undefined}
      afterClose={() => setSkipMotion(false)}
      footer={
        payload ? (
          <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'flex-end', gap: 8 }}>
            {payload.buttons.map((btn, index) => {
              const label = btn.text || '确定';
              const danger = btn.style === 'destructive';
              const cancel = btn.style === 'cancel';
              const primary = danger || (!btn.style && !cancel);
              return (
                <Button
                  key={`${label}-${index}`}
                  type={primary ? 'primary' : 'default'}
                  danger={danger}
                  onClick={() => handlePress(btn)}
                >
                  {label}
                </Button>
              );
            })}
          </div>
        ) : null
      }
      destroyOnHidden
    >
      {payload?.message ? (
        <Typography.Paragraph type="secondary" style={{ ...webType.modalSubtitle, marginBottom: 0, whiteSpace: 'pre-wrap' }}>
          {payload.message}
        </Typography.Paragraph>
      ) : null}
    </Modal>
  );
}
