import { App } from 'antd';
import { useEffect } from 'react';
import { router, type Href } from 'expo-router';
import { EmojiText } from '@/chatMessage/components/EmojiText';
import {
  dismissIncomingBanner,
  subscribeIncomingBanner,
} from '@/core/push/incoming-banner';

function IncomingBridge() {
  const { notification } = App.useApp();

  useEffect(() => {
    return subscribeIncomingBanner((payload) => {
      if (!payload) {
        notification.destroy();
        return;
      }
      notification.open({
        key: `incoming-${payload.id}`,
        title: payload.title,
        description: <EmojiText text={payload.body} variant="preview" />,
        duration: Math.max(1, payload.duration / 1000),
        onClick: () => {
          dismissIncomingBanner();
          if (payload.taskID) {
            router.push({
              pathname: '/chat/[id]',
              params: { id: payload.taskID },
            } as unknown as Href);
          }
        },
      });
    });
  }, [notification]);

  return null;
}

export function WebIncomingBanner() {
  return <IncomingBridge />;
}
