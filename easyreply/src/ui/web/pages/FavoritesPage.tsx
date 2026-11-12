import { useMemo } from 'react';
import { Button, Flex, Listy, Space, Spin, Typography } from 'antd';
import { useFavoritesList } from '@/features/conversations/useFavoritesList';
import { PageFrame } from '@/ui/web/PageFrame';
import { EmptyHint } from '@/ui/web/pages/helpers';
import { webColor, webLayout, webPageBg, webType } from '@/ui/web/theme';

/** 桌面 Web 已改为弹窗；保留页面供窄屏回退路由等场景 */
export default function FavoritesPage() {
  const { rows, loading, handleRemove } = useFavoritesList();
  const countLabel = useMemo(() => `共 ${rows.length} 人`, [rows.length]);

  return (
    <PageFrame title="我的收藏">
      <Flex vertical style={{ ...webLayout.pageBody, background: webPageBg.favorites }} gap={8}>
        <Typography.Text type="secondary" style={webType.subLabel}>
          {countLabel} · 会话列表右键可快捷收藏
        </Typography.Text>
        {loading ? (
          <Flex flex={1} align="center" justify="center">
            <Spin />
          </Flex>
        ) : rows.length === 0 ? (
          <EmptyHint text="暂无收藏" />
        ) : (
          <Listy
            items={rows}
            rowKey="audiencePlatformID"
            virtual={false}
            itemRender={(item) => (
              <Flex
                justify="space-between"
                align="center"
                style={{ padding: '10px 0', borderBottom: `1px solid ${webColor.separator}` }}
              >
                <Typography.Text style={webType.nameLabel}>{item.nickname}</Typography.Text>
                <Space>
                  <Button size="small" danger onClick={() => handleRemove(item)}>
                    取消收藏
                  </Button>
                </Space>
              </Flex>
            )}
          />
        )}
      </Flex>
    </PageFrame>
  );
}
