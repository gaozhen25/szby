import { createElement } from 'react';
import { Flex, Image, Modal } from 'antd';
import type { MediaPreviewState } from '@/chatMessage/components/MediaPreviewModal';
import { webColor } from '@/ui/web/theme';

export function WebMediaPreview({
  state,
  onClose,
}: {
  state: MediaPreviewState;
  onClose: () => void;
}) {
  if (!state.visible) return null;

  if (state.kind === 'image') {
    return (
      <Image
        style={{ display: 'none' }}
        src={state.uri}
        preview={{
          visible: true,
          src: state.uri,
          onVisibleChange: (v) => {
            if (!v) onClose();
          },
        }}
      />
    );
  }

  return (
    <Modal open title={state.fileName || '视频'} footer={null} onCancel={onClose} width={720}>
      <Flex justify="center" style={{ background: webColor.videoBg }}>
        {createElement('video', {
          src: state.uri,
          controls: true,
          autoPlay: true,
          style: { width: '100%', maxHeight: 480, background: webColor.videoBg },
        })}
      </Flex>
    </Modal>
  );
}
