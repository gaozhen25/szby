import { useCallback, useEffect, useMemo, useState } from 'react';
import { getAgentId } from '@/core/im';
import {
  fetchTransferAgents,
  filterTransferAgents,
  sortTransferAgents,
  type TransferAgent,
} from '@/features/conversations/transfer-agent';

/** 打开转派弹窗时拉一次客服列表，支持搜索与单选 */
export function useTransferAgentPicker(opts: {
  visible: boolean;
  currentAgentId?: string;
}) {
  const { visible, currentAgentId: currentAgentIdProp } = opts;
  const currentAgentId = (currentAgentIdProp ?? getAgentId()).trim();
  const [agents, setAgents] = useState<TransferAgent[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [keyword, setKeyword] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await fetchTransferAgents();
      setAgents(list);
    } catch (e) {
      setAgents([]);
      setError(e instanceof Error ? e.message : '加载客服列表失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!visible) return;
    setKeyword('');
    setSelectedId(null);
    void load();
  }, [visible, load]);

  const filtered = useMemo(() => {
    const list = filterTransferAgents(agents, keyword);
    return sortTransferAgents(list, currentAgentId);
  }, [agents, keyword, currentAgentId]);

  const selected = useMemo(
    () => filtered.find((a) => a.agent_id === selectedId) ?? null,
    [filtered, selectedId],
  );

  return {
    currentAgentId,
    loading,
    error,
    keyword,
    setKeyword,
    filtered,
    selected,
    selectedId,
    setSelectedId,
    reload: load,
  };
}
