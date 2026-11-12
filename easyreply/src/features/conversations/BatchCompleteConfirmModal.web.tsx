import { Button, Modal, Typography } from 'antd';

import { formatBatchCompleteMessage, type BatchCompleteConfirmModalProps } from '@/features/conversations/batch-complete';
import { webModalCloseStyle, webType } from '@/ui/web/theme';

export function BatchCompleteConfirmModal({
  visible,
  total,
  done,
  completing,
  onCancel,
  onConfirm,
}: BatchCompleteConfirmModalProps) {
  return (
    <Modal
      open={visible}
      title="批量结束"
      mask={{ closable: false }}
      closable={!completing}
      onCancel={completing ? undefined : onCancel}
      styles={{ title: webType.modalTitle, close: webModalCloseStyle }}
      footer={[
        <Button key="cancel" disabled={completing} onClick={onCancel}>
          取消
        </Button>,
        <Button key="ok" type="primary" danger loading={completing} disabled={completing} onClick={onConfirm}>
          结束
        </Button>,
      ]}
    >
      <Typography.Paragraph type="secondary" style={{ ...webType.modalSubtitle, marginBottom: 0, whiteSpace: 'pre-wrap' }}>
        {formatBatchCompleteMessage(total, done, completing)}
      </Typography.Paragraph>
    </Modal>
  );
}
