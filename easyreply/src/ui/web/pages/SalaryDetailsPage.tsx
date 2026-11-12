import { useMemo, useState } from 'react';
import { Flex, Segmented, Table, Tag } from 'antd';
import { MOCK_SALARY_DETAILS, type SalaryDetailFilter } from '@/mock/data';
import { PageFrame } from '@/ui/web/PageFrame';
import { maybeDevOnly } from '@/ui/web/pages/helpers';
import { webLayout, webPageBg } from '@/ui/web/theme';

function formatAmount(num: number): string {
  const abs = Math.abs(num);
  const sign = num >= 0 ? '+' : '-';
  return `${sign}¥${abs.toFixed(2)}`;
}

function SalaryContent() {
  const [filter, setFilter] = useState<SalaryDetailFilter>('全部');
  const data = useMemo(
    () => (filter === '全部' ? MOCK_SALARY_DETAILS : MOCK_SALARY_DETAILS.filter((i) => i.type === filter)),
    [filter],
  );

  return (
    <PageFrame title="工资明细">
      <Flex vertical gap={12} style={{ ...webLayout.pageBody, background: webPageBg.salaryDetails }}>
        <Segmented
          value={filter}
          onChange={(v) => setFilter(v as SalaryDetailFilter)}
          options={['全部', '在线工资', '扣减额', '回复工资']}
        />
        <Table
          rowKey="id"
          dataSource={data}
          pagination={false}
          columns={[
            { title: '类型', dataIndex: 'type', render: (t: string) => <Tag>{t}</Tag> },
            { title: '金额', dataIndex: 'amount', render: (n: number) => formatAmount(n) },
            { title: '周期', render: (_, r) => `${r.periodStart} ~ ${r.periodEnd}` },
            { title: '入账时间', dataIndex: 'creditedAt' },
          ]}
        />
      </Flex>
    </PageFrame>
  );
}

export default function SalaryDetailsPage() {
  return maybeDevOnly('工资明细', '查看工资入账与扣减', <SalaryContent />, { withShell: true, showBack: true });
}
