// ============================================================
// 转派目标客服：列表拉取、筛选排序、错误文案
// 供单聊「转移会话」与后续批量转移共用
// ============================================================
import { listAppAgents, type AppAgentListItem } from '@/api/agents';
import { getAgentId } from '@/core/im';
import { ApiError } from '@/lib/http';

export type TransferAgent = AppAgentListItem;

export type TransferAgentPickerProps = {
  visible: boolean;
  /** 当前登录客服 id：列表展示「我」且不可选 */
  currentAgentId?: string;
  confirming?: boolean;
  title?: string;
  onClose: () => void;
  onConfirm: (agent: TransferAgent) => void;
};

export type TransferAgentDutyStatus = 'on_duty' | 'off_duty';

const TRANSFER_ERROR_MAP: Record<string, string> = {
  not_current_assignee: '你不是当前会话持有人，无法转移',
  cannot_transfer_to_self: '不能转移给自己',
  target_agent_off_duty: '目标客服未上班，无法转移',
};

export function formatTransferErrorCode(code?: string, fallback = '转移失败，请稍后重试'): string {
  const key = (code ?? '').trim();
  if (key && TRANSFER_ERROR_MAP[key]) return TRANSFER_ERROR_MAP[key];
  if (key) return key;
  return fallback;
}

export function formatTransferError(e: unknown, fallback = '转移失败，请稍后重试'): string {
  if (!(e instanceof ApiError)) {
    return e instanceof Error ? e.message : fallback;
  }
  const body = e.body as { detail?: string; message?: string; error?: string; code?: string } | null;
  const code =
    (typeof body?.detail === 'string' && body.detail) ||
    (typeof body?.code === 'string' && body.code) ||
    (typeof body?.error === 'string' && body.error) ||
    (typeof body?.message === 'string' && body.message) ||
    '';
  return formatTransferErrorCode(code || e.message, fallback);
}

export function transferAgentDutyStatus(agent: TransferAgent): TransferAgentDutyStatus {
  return agent.on_duty ? 'on_duty' : 'off_duty';
}

export function transferAgentStatusLabel(status: TransferAgentDutyStatus): string {
  return status === 'on_duty' ? '上班' : '未上班';
}

export function formatTransferAgentLoad(agent: TransferAgent): string {
  const current = Number.isFinite(agent.current_task_count) ? agent.current_task_count : 0;
  const max = Number.isFinite(agent.max_active_cap) ? agent.max_active_cap : 0;
  return `${current}/${max}`;
}

export function isTransferAgentAtCap(agent: TransferAgent): boolean {
  const current = Number.isFinite(agent.current_task_count) ? agent.current_task_count : 0;
  const max = Number.isFinite(agent.max_active_cap) ? agent.max_active_cap : 0;
  return max > 0 && current >= max;
}

/** 是否为当前登录客服本人 */
export function isTransferAgentSelf(agent: TransferAgent, currentAgentId?: string): boolean {
  const me = (currentAgentId ?? getAgentId()).trim();
  return !!me && agent.agent_id === me;
}

/** 未上班、已达上限或本人，不可选为转派目标 */
export function isTransferAgentSelectable(agent: TransferAgent, currentAgentId?: string): boolean {
  if (isTransferAgentSelf(agent, currentAgentId)) return false;
  return agent.on_duty && !isTransferAgentAtCap(agent);
}

export function sortTransferAgents(list: TransferAgent[], currentAgentId?: string): TransferAgent[] {
  const me = (currentAgentId ?? getAgentId()).trim();
  return [...list].sort((a, b) => {
    if (me) {
      const aMe = a.agent_id === me ? 1 : 0;
      const bMe = b.agent_id === me ? 1 : 0;
      if (aMe !== bMe) return bMe - aMe;
    }
    const selectable = Number(isTransferAgentSelectable(b, me)) - Number(isTransferAgentSelectable(a, me));
    if (selectable !== 0) return selectable;
    const duty = Number(b.on_duty) - Number(a.on_duty);
    if (duty !== 0) return duty;
    return (a.agent_account || '').localeCompare(b.agent_account || '', 'zh');
  });
}

export function filterTransferAgents(list: TransferAgent[], keyword: string): TransferAgent[] {
  const q = keyword.trim().toLowerCase();
  return list.filter((a) => {
    if (!q) return true;
    return (
      a.agent_account.toLowerCase().includes(q) ||
      a.agent_id.toLowerCase().includes(q)
    );
  });
}

export async function fetchTransferAgents(): Promise<TransferAgent[]> {
  const res = await listAppAgents();
  const agents = Array.isArray(res.agents) ? res.agents : [];
  return sortTransferAgents(
    agents.filter((a) => typeof a.agent_id === 'string' && a.agent_id.trim()),
  );
}
