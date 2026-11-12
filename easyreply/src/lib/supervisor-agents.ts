// ============================================================
// 主管 overview 接口 → 标注员列表 UI 模型
// ============================================================
import type { SupervisorAgentOverview } from '@/api/supervisor';
import type { AnnotatorStatus, MockAnnotator } from '@/mock/data';

function resolveAnnotatorStatus(agent: SupervisorAgentOverview): AnnotatorStatus {
  if (agent.profile?.valid === false) return 'disabled';
  if (agent.on_duty) return 'online';
  return 'offline';
}

/** 将 overview 单条 agent 转为标注员卡片数据（备注优先本地缓存，其次接口 additional_info） */
export function mapOverviewAgentToAnnotator(
  agent: SupervisorAgentOverview,
  localRemark = '',
): MockAnnotator {
  const status = resolveAnnotatorStatus(agent);
  const name = agent.agent_accout?.trim() ?? '';
  const remark = localRemark.trim() || agent.additional_info?.trim() || '';

  return {
    id: agent.agent_id,
    agentId: agent.agent_id,
    name,
    phone: '—',
    status,
    remark,
    intakePaused: !!agent.intake_paused,
    maxActiveCap:
      typeof agent.profile?.max_active_cap === 'number' && Number.isFinite(agent.profile.max_active_cap)
        ? agent.profile.max_active_cap
        : null,
    onlineDuration: agent.on_duty
      ? agent.intake_paused
        ? '上班·暂停接待'
        : '上班中'
      : '已下班',
    replyCount: agent.task_count ?? agent.tasks?.length ?? 0,
    todaySalary: '—',
    lastActiveAt: agent.on_duty ? (agent.intake_paused ? '暂停接待' : '在线') : '离线',
  };
}

export function mapOverviewAgentsToAnnotators(
  agents: SupervisorAgentOverview[],
  remarks: Record<string, string> = {},
): MockAnnotator[] {
  return agents.map((a) => mapOverviewAgentToAnnotator(a, remarks[a.agent_id] ?? ''));
}
