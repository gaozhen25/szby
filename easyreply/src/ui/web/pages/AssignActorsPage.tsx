import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Button, Flex, Input, Switch, Table, Typography } from 'antd';
import { useLocalSearchParams } from 'expo-router';
import { fetchActorsList, type ActorItem } from '@/api/actors';
import {
  formatExclusiveActorError,
  grantExclusiveActor,
  listExclusiveActors,
  revokeExclusiveActor,
} from '@/api/supervisor';
import { appAlert } from '@/lib/app-alert';
import { PageFrame } from '@/ui/web/PageFrame';
import { webLayout, webPageBg, webType } from '@/ui/web/theme';

const PAGE_SIZE = 20;

export default function AssignActorsPage() {
  const { agentId, name } = useLocalSearchParams<{ agentId: string; name?: string }>();
  const targetAgentId = (agentId ?? '').trim();
  const agentName = name?.trim() || '客服';
  const [actors, setActors] = useState<ActorItem[]>([]);
  const [total, setTotal] = useState(0);
  const [exclusiveIds, setExclusiveIds] = useState<Set<string>>(() => new Set());
  const [keyword, setKeyword] = useState('');
  const [loading, setLoading] = useState(true);
  const togglingRef = useRef<Set<string>>(new Set());

  const loadExclusiveIds = useCallback(async () => {
    if (!targetAgentId) return new Set<string>();
    const res = await listExclusiveActors(targetAgentId);
    const ids = Array.isArray(res.exclusive_actor_ids) ? res.exclusive_actor_ids : [];
    return new Set(ids.map((id) => id.trim()).filter(Boolean));
  }, [targetAgentId]);

  const loadPage = useCallback(async (offset: number) => {
    const res = await fetchActorsList({ limit: PAGE_SIZE, offset });
    return {
      list: Array.isArray(res?.actors) ? res.actors : [],
      total: typeof res?.total === 'number' ? res.total : 0,
    };
  }, []);

  useEffect(() => {
    let alive = true;
    (async () => {
      setLoading(true);
      try {
        const [{ list, total: nextTotal }, exclusive] = await Promise.all([loadPage(0), loadExclusiveIds()]);
        if (!alive) return;
        setActors(list);
        setTotal(nextTotal);
        setExclusiveIds(exclusive);
      } catch (e) {
        if (!alive) return;
        appAlert('加载失败', formatExclusiveActorError(e));
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [loadPage, loadExclusiveIds]);

  const filtered = useMemo(() => {
    const q = keyword.trim().toLowerCase();
    if (!q) return actors;
    return actors.filter((a) => {
      const shop = (a.shopName ?? '').toLowerCase();
      const id = (a.actorID ?? '').toLowerCase();
      return shop.includes(q) || id.includes(q);
    });
  }, [actors, keyword]);

  const handleToggle = (actorIdRaw: string) => {
    const actorId = actorIdRaw.trim();
    if (!targetAgentId || !actorId || togglingRef.current.has(actorId)) return;
    const assigned = exclusiveIds.has(actorId);
    setExclusiveIds((prev) => {
      const next = new Set(prev);
      if (assigned) next.delete(actorId);
      else next.add(actorId);
      return next;
    });
    togglingRef.current.add(actorId);
    void (async () => {
      try {
        const res = assigned
          ? await revokeExclusiveActor({ agent_id: targetAgentId, actor_platform_id: actorId })
          : await grantExclusiveActor({ agent_id: targetAgentId, actor_platform_id: actorId });
        if (Array.isArray(res.exclusive_actor_ids)) {
          setExclusiveIds(new Set(res.exclusive_actor_ids.map((id) => id.trim()).filter(Boolean)));
        }
      } catch (e) {
        setExclusiveIds((prev) => {
          const next = new Set(prev);
          if (assigned) next.add(actorId);
          else next.delete(actorId);
          return next;
        });
        appAlert(assigned ? '取消指派失败' : '指派失败', formatExclusiveActorError(e));
      } finally {
        togglingRef.current.delete(actorId);
      }
    })();
  };

  return (
    <PageFrame title="指派客户">
      <Flex vertical gap={12} style={{ ...webLayout.pageBody, background: webPageBg.assignActors }}>
        <Typography.Text type="secondary" style={webType.subLabel}>
          为「{agentName}」指派独占客户，指派后该客户任务仅分配给此客服
        </Typography.Text>
        <Input.Search placeholder="搜索客户" allowClear value={keyword} onChange={(e) => setKeyword(e.target.value)} />
        <Table
          rowKey="actorID"
          loading={loading}
          dataSource={filtered}
          pagination={{
            total,
            pageSize: PAGE_SIZE,
            onChange: (page) => {
              void loadPage((page - 1) * PAGE_SIZE).then(({ list, total: t }) => {
                setActors(list);
                setTotal(t);
              });
            },
          }}
          columns={[
            { title: '客户', dataIndex: 'shopName' },
            { title: 'ID', dataIndex: 'actorID', ellipsis: true },
            {
              title: '已指派',
              render: (_, a) => (
                <Switch
                  checked={exclusiveIds.has(a.actorID)}
                  onChange={() => handleToggle(a.actorID)}
                />
              ),
            },
          ]}
        />
        <Button
          onClick={() => {
            void loadPage(actors.length).then(({ list, total: t }) => {
              setActors((prev) => {
                const seen = new Set(prev.map((x) => x.actorID));
                return [...prev, ...list.filter((x) => !seen.has(x.actorID))];
              });
              setTotal(t);
            });
          }}
        >
          加载更多
        </Button>
      </Flex>
    </PageFrame>
  );
}
