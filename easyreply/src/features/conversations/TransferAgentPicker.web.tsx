import { Button, Empty, Flex, Input, Modal, Radio, Spin, Typography } from 'antd';
import { SearchOutlined } from '@/ui/web/antd-icons';
import { webColor, webModalCloseStyle, webType } from '@/ui/web/theme';
import { useTransferAgentPicker } from '@/features/conversations/useTransferAgentPicker';
import {
  formatTransferAgentLoad,
  isTransferAgentSelectable,
  isTransferAgentSelf,
  transferAgentDutyStatus,
  transferAgentStatusLabel,
  type TransferAgentPickerProps,
} from '@/features/conversations/transfer-agent';

function statusColor(status: ReturnType<typeof transferAgentDutyStatus>): string {
  return status === 'on_duty' ? webColor.success : webColor.subLabel;
}

export function TransferAgentPicker({
  visible,
  currentAgentId,
  confirming = false,
  title = '转移会话',
  onClose,
  onConfirm,
}: TransferAgentPickerProps) {
  const picker = useTransferAgentPicker({ visible, currentAgentId });
  const canConfirm =
    !!picker.selected && isTransferAgentSelectable(picker.selected, picker.currentAgentId) && !confirming;

  return (
    <Modal
      open={visible}
      title={title}
      mask={{ closable: false }}
      closable={!confirming}
      onCancel={confirming ? undefined : onClose}
      styles={{ title: webType.modalTitle, close: webModalCloseStyle }}
      footer={[
        <Button key="cancel" disabled={confirming} onClick={onClose}>
          取消
        </Button>,
        <Button
          key="ok"
          type="primary"
          loading={confirming}
          disabled={!canConfirm}
          onClick={() => {
            if (
              picker.selected &&
              isTransferAgentSelectable(picker.selected, picker.currentAgentId)
            ) {
              onConfirm(picker.selected);
            }
          }}
        >
          确认转移
        </Button>,
      ]}
    >
      <Typography.Paragraph type="secondary" style={{ ...webType.modalSubtitle, marginBottom: 12 }}>
        选择要转给的客服
      </Typography.Paragraph>
      <Input
        allowClear
        prefix={<SearchOutlined />}
        placeholder="搜索账号"
        value={picker.keyword}
        onChange={(e) => picker.setKeyword(e.target.value)}
        disabled={confirming}
        style={{ marginBottom: 12 }}
      />
      <div style={{ maxHeight: 360, overflowY: 'auto', minHeight: 160 }}>
        {picker.loading ? (
          <Flex align="center" justify="center" style={{ height: 160 }}>
            <Spin />
          </Flex>
        ) : picker.error ? (
          <Flex vertical align="center" justify="center" gap={8} style={{ height: 160 }}>
            <Typography.Text type="danger">{picker.error}</Typography.Text>
            <Button type="link" onClick={() => void picker.reload()}>
              点击重试
            </Button>
          </Flex>
        ) : picker.filtered.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无可转派客服" />
        ) : (
          <Radio.Group
            value={picker.selectedId}
            onChange={(e) => {
              const id = e.target.value as string;
              const next = picker.filtered.find((a) => a.agent_id === id);
              if (!next || !isTransferAgentSelectable(next, picker.currentAgentId)) return;
              picker.setSelectedId(id);
            }}
            disabled={confirming}
            style={{ width: '100%' }}
          >
            <Flex vertical>
              {picker.filtered.map((item) => {
                const status = transferAgentDutyStatus(item);
                const isSelf = isTransferAgentSelf(item, picker.currentAgentId);
                const selectable = isTransferAgentSelectable(item, picker.currentAgentId);
                const color = statusColor(status);
                const selected = picker.selectedId === item.agent_id && selectable;
                return (
                  <label
                    key={item.agent_id}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 10,
                      padding: '10px 8px',
                      borderRadius: 8,
                      cursor: confirming || !selectable ? 'not-allowed' : 'pointer',
                      opacity: selectable ? 1 : 0.45,
                      background: selected ? webColor.primarySoft : 'transparent',
                    }}
                  >
                    <Radio value={item.agent_id} disabled={!selectable || confirming} />
                    <Flex vertical flex={1} style={{ minWidth: 0 }} gap={2}>
                      <Flex align="center" gap={8}>
                        <Flex align="center" gap={6} style={{ flex: 1, minWidth: 0 }}>
                          <Typography.Text ellipsis style={webType.nameLabel}>
                            {item.agent_account || item.agent_id}
                          </Typography.Text>
                          {isSelf ? (
                            <span
                              style={{
                                flexShrink: 0,
                                padding: '1px 6px',
                                borderRadius: 4,
                                fontSize: 11,
                                fontWeight: 600,
                                lineHeight: '16px',
                                color: webColor.primary,
                                background: webColor.primarySoft,
                              }}
                            >
                              我
                            </span>
                          ) : null}
                        </Flex>
                        <span
                          style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: 4,
                            padding: '1px 8px',
                            borderRadius: 999,
                            fontSize: 11,
                            fontWeight: 600,
                            color,
                            background: `${color}18`,
                            flexShrink: 0,
                          }}
                        >
                          <span
                            style={{
                              width: 6,
                              height: 6,
                              borderRadius: 3,
                              background: color,
                            }}
                          />
                          {transferAgentStatusLabel(status)}
                        </span>
                      </Flex>
                      <Typography.Text style={webType.subLabel}>
                        会话 {formatTransferAgentLoad(item)}
                      </Typography.Text>
                    </Flex>
                  </label>
                );
              })}
            </Flex>
          </Radio.Group>
        )}
      </div>
    </Modal>
  );
}

export type { TransferAgentPickerProps };
