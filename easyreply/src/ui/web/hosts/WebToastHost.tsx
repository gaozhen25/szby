import { App } from 'antd';
import { useEffect } from 'react';
import { subscribeAppToast } from '@/lib/app-toast';

function ToastBridge() {
  const { message } = App.useApp();

  useEffect(() => {
    return subscribeAppToast((payload) => {
      if (!payload) return;
      const duration = (payload.duration ?? 2000) / 1000;
      if (payload.variant === 'danger') {
        void message.error(payload.message, duration);
      } else if (payload.variant === 'success') {
        void message.success(payload.message, duration);
      } else {
        void message.info(payload.message, duration);
      }
    });
  }, [message]);

  return null;
}

export function WebToastHost() {
  return <ToastBridge />;
}
