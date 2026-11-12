import { useMemo, useState } from 'react';
import { Button, Card, Flex, Segmented, Statistic, Table, Tag } from 'antd';
import { MOCK_SETTLEMENT_ITEMS, type MockSettlementItem, type SettlementStatus } from '@/mock/data';
import { appAlert } from '@/lib/app-alert';
import { PageFrame } from '@/ui/web/PageFrame';
import { maybeDevOnly } from '@/ui/web/pages/helpers';
import { webLayout, webPageBg } from '@/ui/web/theme';

type StatusFilter = 'all' | SettlementStatus;

function formatMoney(value: number): string {
  const sign = value >= 0 ? '' : '-';
  return `${sign}¥${Math.abs(value).toFixed(2)}`;
}

function calcTotal(item: MockSettlementItem): number {
  return item.onlineSalary + item.replySalary - item.deduction;
}

function SettlementContent() {
  const [filter, setFilter] = useState<StatusFilter>('all');
  const [items, setItems] = useState(MOCK_SETTLEMENT_ITEMS);

  const filtered = useMemo(
    () => (filter === 'all' ? items : items.filter((i) => i.status === filter)),
    [filter, items],
  );

  const pending = items.filter((i) => i.status === 'pending');
  const pendingAmount = pending.reduce((s, i) => s + calcTotal(i), 0);

  return (
    <PageFrame title="绩效核算" showBack={false} withShell={false}>
      <Flex vertical style={{ ...webLayout.pageBody, background: webPageBg.performanceSettlement }}>
        <Card style={{ marginBottom: 16 }}>
          <Statistic title="待核算" value={pending.length} />
          <Statistic title="待结金额" value={formatMoney(pendingAmount)} />
        </Card>
        <Segmented
          style={{ marginBottom: 16 }}
          value={filter}
          onChange={(v) => setFilter(v as StatusFilter)}
          options={[
            { label: '全部', value: 'all' },
            { label: '待核算', value: 'pending' },
            { label: '已核算', value: 'settled' },
          ]}
        />
        <Table
          rowKey="id"
          dataSource={filtered}
          pagination={false}
          columns={[
            { title: '客服', dataIndex: 'annotatorName' },
            { title: '在线工资', render: (_, r) => formatMoney(r.onlineSalary) },
            { title: '回复工资', render: (_, r) => formatMoney(r.replySalary) },
            { title: '扣减', render: (_, r) => formatMoney(r.deduction) },
            { title: '合计', render: (_, r) => formatMoney(calcTotal(r)) },
            {
              title: '状态',
              render: (_, r) => (
                <Tag color={r.status === 'settled' ? 'success' : 'warning'}>
                  {r.status === 'settled' ? '已核算' : '待核算'}
                </Tag>
              ),
            },
            {
              title: '操作',
              render: (_, r) =>
                r.status === 'pending' ? (
                  <Button
                    size="small"
                    type="primary"
                    onClick={() => {
                      appAlert('确认核算', `确定核算「${r.annotatorName}」的绩效？`, [
                        { text: '取消', style: 'cancel' },
                        {
                          text: '确认',
                          onPress: () =>
                            setItems((prev) =>
                              prev.map((x) => (x.id === r.id ? { ...x, status: 'settled' } : x)),
                            ),
                        },
                      ]);
                    }}
                  >
                    核算
                  </Button>
                ) : null,
            },
          ]}
        />
      </Flex>
    </PageFrame>
  );
}

export default function PerformanceSettlementPage() {
  return maybeDevOnly('绩效核算', '主管查看与核算下级标注员绩效', <SettlementContent />);
}
