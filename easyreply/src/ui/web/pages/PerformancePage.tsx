import { useCallback, useState } from 'react';
import { Button, Card, Col, Flex, Row, Statistic, Switch, Typography } from 'antd';
import { EyeInvisibleOutlined, EyeOutlined, ReloadOutlined } from '@/ui/web/antd-icons';
import { router } from 'expo-router';
import { MOCK_PERFORMANCE } from '@/mock/data';
import { PageFrame } from '@/ui/web/PageFrame';
import { maybeDevOnly } from '@/ui/web/pages/helpers';
import { webLayout, webPageBg, webType } from '@/ui/web/theme';

function PerformanceContent() {
  const [refreshing, setRefreshing] = useState(false);
  const [amountVisible, setAmountVisible] = useState(true);
  const stats = MOCK_PERFORMANCE;

  const handleRefresh = useCallback(() => {
    setRefreshing(true);
    setTimeout(() => setRefreshing(false), 800);
  }, []);

  const money = (v: string) => (amountVisible ? v : '¥****');

  return (
    <PageFrame
      title="绩效中心"
      showBack={false}
      withShell={false}
      extra={
        <Button icon={<ReloadOutlined />} loading={refreshing} onClick={handleRefresh}>
          刷新
        </Button>
      }
    >
      <Flex vertical gap={16} style={{ ...webLayout.pageBody, background: webPageBg.performance }}>
        <Card>
          <Flex justify="space-between" align="center" style={{ marginBottom: 12 }}>
            <Typography.Title level={5} style={webType.sectionTitle}>今日收入</Typography.Title>
            <Switch
              checked={amountVisible}
              onChange={setAmountVisible}
              checkedChildren={<EyeOutlined />}
              unCheckedChildren={<EyeInvisibleOutlined />}
            />
          </Flex>
          <Statistic title="今日工资" value={amountVisible ? stats.salary : '****'} />
          <Typography.Text type="secondary">
            可提现 {amountVisible ? stats.withdrawable : '¥****'}
          </Typography.Text>
        </Card>
        <Row gutter={12}>
          <Col span={12}><Card><Statistic title="在线时长" value={stats.onlineDuration} /></Card></Col>
          <Col span={12}><Card><Statistic title="回复数" value={amountVisible ? stats.replyCount : '**'} suffix="条" /></Card></Col>
        </Row>
        <Row gutter={12}>
          <Col span={12}><Card><Statistic title="扣减额" value={money(stats.deduction)} /></Card></Col>
          <Col span={12}><Card><Statistic title="已提现" value={money(stats.withdrawn)} /></Card></Col>
        </Row>
        <Button type="link" onClick={() => router.push('/feature/performance/salary-details')}>
          工资明细
        </Button>
        <Typography.Paragraph type="secondary">
          工资按在线时长与回复质量结算，扣减记录可在明细中查看。
        </Typography.Paragraph>
      </Flex>
    </PageFrame>
  );
}

export default function PerformancePage() {
  return maybeDevOnly('绩效中心', '实时查看今日工作表现与收入', <PerformanceContent />);
}
