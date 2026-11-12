// ============================================================
// Agent 信息查询工具（统一入口）
// ============================================================
import { fetchAdminAgent } from '@/api/agents';
import type { AgentInfo } from '@/api/auth';

export type { AgentInfo } from '@/api/auth';

/** 账号名基本不变；缓存 10 分钟，兼顾「弹窗要立刻拿到名字」与后台改名后能刷新 */
const CACHE_TTL_MS = 10 * 60 * 1000;
const cache = new Map<string, { info: AgentInfo; at: number }>();
const inFlight = new Map<string, Promise<AgentInfo | null>>();

/** 已缓存的 agent 信息；无缓存或已过期返回 null（供需要同步取值的场景） */
export function getCachedAgentInfoById(agentId: string): AgentInfo | null {
  const id = agentId?.trim();
  if (!id) return null;
  const hit = cache.get(id);
  if (!hit || Date.now() - hit.at > CACHE_TTL_MS) return null;
  return hit.info;
}

/**
 * 根据 agentId 获取对应客服/标注员信息。
 * 统一封装 GET /api/admin/agents/{agent_id}，供业务侧直接调用。
 * 命中缓存直接返回；并发同 id 复用同一请求。
 *
 * @returns 成功且 ok=true 时返回 item 实体；agentId 为空或 ok=false 时返回 null
 */
export async function getAgentInfoById(agentId: string): Promise<AgentInfo | null> {
  const id = agentId?.trim();
  if (!id) return null;

  const cached = getCachedAgentInfoById(id);
  if (cached) return cached;

  const existing = inFlight.get(id);
  if (existing) return existing;

  const task = (async () => {
    const res = await fetchAdminAgent(id);
    if (!res.ok || !res.item) return null;
    cache.set(id, { info: res.item, at: Date.now() });
    return res.item;
  })();
  inFlight.set(id, task.finally(() => inFlight.delete(id)) as Promise<AgentInfo | null>);
  return task;
}

/** 提前预热账号信息（如主管加载下属列表后），让后续弹窗能同步拿到账号名 */
export function warmAgentInfoCache(agentIds: (string | undefined | null)[]): void {
  for (const raw of agentIds) {
    const id = raw?.trim();
    if (!id || getCachedAgentInfoById(id) || inFlight.has(id)) continue;
    void getAgentInfoById(id).catch(() => null);
  }
}

/**
 * 根据 agentId 获取信息；查不到时抛错（便于必须拿到实体的场景）。
 */
export async function requireAgentInfoById(agentId: string): Promise<AgentInfo> {
  const info = await getAgentInfoById(agentId);
  if (!info) throw new Error(`未找到 agent 信息：${agentId}`);
  return info;
}
