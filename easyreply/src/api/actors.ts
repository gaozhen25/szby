// ============================================================
// Actor / Audience 代理上游接口
// POST /api/app/actors/list
// POST /api/app/upstream_cs/audience/platform_accounts/remark
// ============================================================
import { post } from '@/lib/http';

export interface ActorItem {
  actorID: string;
  shopName?: string;
  csEnabled?: boolean;
  skillGroup?: string;
  agentKey?: string;
  createTime?: number;
  updateTime?: number;
}

export interface ActorsListParams {
  limit?: number;
  offset?: number;
}

export interface ActorsListResult {
  total: number;
  actors: ActorItem[];
}

/** 分页获取 Actor（店铺/商家账号）列表 */
export function fetchActorsList(params: ActorsListParams = {}): Promise<ActorsListResult> {
  return post<ActorsListResult>('/api/app/actors/list', {
    limit: params.limit ?? 20,
    offset: params.offset ?? 0,
  });
}

/** 修改 Audience 平台账号备注入参 */
export interface UpdateAudienceRemarkParams {
  /** 平台标识：wechat / wecom / douyin 等 */
  platform: string;
  audience_platform_id: string;
  remark: string;
}

export interface UpdateAudienceRemarkResult {
  ok?: boolean;
  [key: string]: unknown;
}

/**
 * 修改 Audience 平台账号备注。
 * POST /api/app/upstream_cs/audience/platform_accounts/remark
 */
export function updateAudiencePlatformRemark(
  params: UpdateAudienceRemarkParams,
): Promise<UpdateAudienceRemarkResult> {
  return post<UpdateAudienceRemarkResult>(
    '/api/app/upstream_cs/audience/platform_accounts/remark',
    {
      platform: params.platform.trim(),
      audience_platform_id: params.audience_platform_id.trim(),
      remark: params.remark,
    },
  );
}
