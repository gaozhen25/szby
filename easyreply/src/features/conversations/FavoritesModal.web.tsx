import { useMemo } from 'react';
import { Button, Flex, Modal, Spin, Typography } from 'antd';
import { useFavoritesList } from '@/features/conversations/useFavoritesList';
import { EmptyHint } from '@/ui/web/pages/helpers';
import { webColor, webModalCloseStyle, webType } from '@/ui/web/theme';

export type FavoritesModalProps = {
  visible: boolean;
  onClose: () => void;
  onFavoritesChange?: (ids: string[]) => void;
};

export function FavoritesModal({ visible, onClose, onFavoritesChange }: FavoritesModalProps) {
  const { rows, loading, handleRemove } = useFavoritesList({
    active: visible,
    onIdsChange: onFavoritesChange,
  });
  const countLabel = useMemo(() => `共 ${rows.length} 人`, [rows.length]);

  return (
    <Modal
      open={visible}
      title="我的收藏"
      mask={{ closable: false }}
      onCancel={onClose}
      styles={{ title: webType.modalTitle, close: webModalCloseStyle }}
      footer={[
        <Button key="close" type="primary" onClick={onClose}>
          关闭
        </Button>,
      ]}
      width={480}
      destroyOnHidden
    >
      <Typography.Text type="secondary" style={{ ...webType.modalSubtitle, display: 'block' }}>
        {countLabel} · 会话列表右键可快捷收藏
      </Typography.Text>
      <div style={{ maxHeight: 400, overflowY: 'auto', marginTop: 12, minHeight: 120 }}>
        {loading ? (
          <Flex align="center" justify="center" style={{ height: 160 }}>
            <Spin />
          </Flex>
        ) : rows.length === 0 ? (
          <EmptyHint text="暂无收藏" />
        ) : (
          <Flex vertical>
            {rows.map((item) => (
              <Flex
                key={item.audiencePlatformID}
                justify="space-between"
                align="center"
                style={{ padding: '10px 0', borderBottom: `1px solid ${webColor.separator}` }}
              >
                <Typography.Text style={webType.nameLabel}>{item.nickname}</Typography.Text>
                <Button size="small" danger onClick={() => handleRemove(item)}>
                  取消收藏
                </Button>
              </Flex>
            ))}
          </Flex>
        )}
      </div>
    </Modal>
  );
}
