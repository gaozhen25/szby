// ============================================================
// 页面 Mock 数据（接口就绪后替换）
// ============================================================
import type { AdoptionContext, IMServerMessage, ProactiveActionHint } from '@/core/im/types';

export type ChatPlatform = '微信' | '抖音';

export interface ChatFilterOption {
  id: string;
  label: string;
}

/** 小类，关联所属大类（接口就绪后由服务端返回） */
export interface ChatSubCategory extends ChatFilterOption {
  majorId: string;
}

export const MOCK_CHAT_MAJOR_FILTERS: ChatFilterOption[] = [
  { id: 'all', label: '全部' },
  { id: 'lose-weight', label: '减肥' },
];

export const MOCK_CHAT_SUB_FILTERS: ChatSubCategory[] = [
  { id: 'all', label: '全部', majorId: 'all' },
  { id: 'coach-liu', label: '刘教带你瘦（监督减肥）', majorId: 'lose-weight' },
  { id: 'noi', label: 'Noi', majorId: 'lose-weight' },
];

/** 会话 categoryId → 所属大类 */
export const CHAT_CATEGORY_MAJOR_MAP: Record<string, string> = {
  'lose-weight': 'lose-weight',
  'coach-liu': 'lose-weight',
  noi: 'lose-weight',
};

/** @deprecated 兼容旧引用，请使用 MOCK_CHAT_MAJOR_FILTERS / MOCK_CHAT_SUB_FILTERS */
export type ChatSessionFilter = ChatFilterOption;

/** @deprecated 兼容旧引用 */
export const MOCK_CHAT_FILTERS: ChatFilterOption[] = [
  ...MOCK_CHAT_MAJOR_FILTERS,
  ...MOCK_CHAT_SUB_FILTERS.filter((f) => f.id !== 'all'),
];

export interface MockConversation {
  id: string;
  from: string;
  to: string;
  platform: ChatPlatform;
  preview: string;
  time: string;
  unread: number;
  avatarColor: string;
  categoryId: string;
  /** IM 会话 id，用于 annotation_event 匹配 */
  imConversationID?: string;
  /** 最后一条消息实体（列表预览/时间来源，本地缓存持久化） */
  lastMessage?: IMServerMessage;
  /**
   * 是否已失效（列表置灰、归入历史区）：
   * - false：当前仍归属自己，可正常接待/聊天
   * - true：任务已不在自己名下（如 annotation_event eventType=2/3 回收、claimed/list 不再返回、主管接管等），无法继续聊天
   */
  inactive?: boolean;
  /**
   * 红点：收到用户主动消息且尚未处理。
   * 语义为「未处理」，非「未读」——仅进入会话查看不会清除；
   * 客服回复（direction=1）、emitConversationProcessed、或 task_ack_pending 成功（ack_pending_result ok）会清除。
   * 判定见 resolveConversationHasRedDot：对方末条 + 与 redDotAckServerMsgID 水位比较。
   */
  hasRedDot?: boolean;
  /**
   * 红点已处理水位（本地字段，claimed/list 不返回）：
   * 清除红点时写入当时 lastMessage.serverMsgID；
   * 之后仅当对方新末条 serverMsgID 与此不同时再亮红点，避免 list 刷新把已处理又盖回红点。
   */
  redDotAckServerMsgID?: string;
  /** 教练/我方平台 id（Actor 列表去重 / 筛选） */
  actorPlatformID?: string;
  /** 教练/我方平台昵称（搜索用） */
  actorPlatformNickname?: string;
  /** 教练/我方头像（Actor 列表展示用） */
  actorPlatformFaceURL?: string;
  /** 学员/对方平台昵称（搜索用） */
  audiencePlatformNickname?: string;
  /** 学员/对方头像（列表展示用） */
  audiencePlatformFaceURL?: string;
  /** 学员/对方平台 id（收藏 Audience 用） */
  audiencePlatformID?: string;
  /** 主管接管来源：被接管客服的 agentId */
  fromAgentId?: string;
  /** 主管接管来源：被接管客服的登录账号 */
  fromAgentAccount?: string;
  /** 被主管接管标记（客服端置灰缓存用） */
  supervisorTakeover?: boolean;
  /**
   * 主管已归还给原客服（主管端缓存标记）：
   * 收到 supervisor_return_to_agent_result ok 后写入；列表置灰、进房提示「已归还给原客服」
   */
  returnedToAgent?: boolean;
  /** 处理模式：human / ai_assisted（来自 task.taskMode / set_task_mode_result） */
  taskMode?: 'human' | 'ai_assisted';
  /**
   * 技能组标识（来自 task.skillGroup）：labor 等同 AI 托管。
   * 缓存下来供进房 / 重进会话在 tasks/detail 返回前也能取到同一门禁。
   */
  skillGroup?: string;
  /**
   * 已在本机复审过的 adoptionID 水位：
   * 聊天页复审「确定 / 已处理」后写入；与 adoptionContext.adoptionID 比较，一致则不再展示复审。
   * claimed/list 不返回该字段，merge 时保留本地值。
   */
  handledAdoptionID?: string;
  /**
   * 待复审上下文（来自 WS ai_review_required / eventType=8，或 claimed/list 未处理的 adoption）：
   * 列表展示「AI复审」标识；进房优先读此字段；处理完成后清除并写入 handledAdoptionID。
   */
  adoptionContext?: AdoptionContext;
  /**
   * 定时主动触达提醒（annotation_event eventType=5）：
   * 列表展示黄点；进房后导航栏下弹出 actionContent 提醒。
   */
  proactiveActionHints?: ProactiveActionHint[];
}

/** 会话是否有黄点（主动触达提醒） */
export function hasConversationProactiveHint(c: Pick<MockConversation, 'proactiveActionHints'>): boolean {
  return Array.isArray(c.proactiveActionHints) && c.proactiveActionHints.some((h) => !!h?.actionContent?.trim());
}

/** 会话是否有待 AI 复审（缓存中存在含候选的 adoptionContext） */
export function hasConversationAdoptionReview(
  c: Pick<MockConversation, 'adoptionContext' | 'handledAdoptionID'>,
): boolean {
  const adoption = c.adoptionContext;
  if (!adoption || !Array.isArray(adoption.candidates) || adoption.candidates.length === 0) {
    return false;
  }
  const id = adoption.adoptionID?.trim();
  if (id && c.handledAdoptionID === id) return false;
  return true;
}

export interface MockPerformanceStats {
  onlineDuration: string;
  replyCount: number;
  salary: string;
  deduction: string;
  withdrawable: string;
  withdrawn: string;
}

export type SalaryDetailType = '在线工资' | '扣减额' | '回复工资';

export type SalaryDetailFilter = '全部' | SalaryDetailType;

export interface MockSalaryDetailItem {
  id: string;
  amount: number;
  type: SalaryDetailType;
  periodStart: string;
  periodEnd: string;
  creditedAt: string;
}

export const MOCK_SALARY_DETAILS: MockSalaryDetailItem[] = [
  {
    id: '1',
    amount: -10,
    type: '扣减额',
    periodStart: '2026/6/10 10:13',
    periodEnd: '10:13',
    creditedAt: '2026/6/10 10:13',
  },
  {
    id: '2',
    amount: 17.85,
    type: '在线工资',
    periodStart: '2026/6/5 05:00',
    periodEnd: '2026/6/6 05:00',
    creditedAt: '2026/6/6 05:00',
  },
  {
    id: '3',
    amount: 36,
    type: '在线工资',
    periodStart: '2026/6/3 05:00',
    periodEnd: '2026/6/4 05:00',
    creditedAt: '2026/6/4 05:00',
  },
  {
    id: '4',
    amount: 36,
    type: '在线工资',
    periodStart: '2026/6/2 05:00',
    periodEnd: '2026/6/3 05:00',
    creditedAt: '2026/6/3 05:00',
  },
  {
    id: '5',
    amount: 22.35,
    type: '在线工资',
    periodStart: '2026/6/1 05:00',
    periodEnd: '2026/6/2 05:00',
    creditedAt: '2026/6/2 05:00',
  },
  {
    id: '6',
    amount: 31.75,
    type: '在线工资',
    periodStart: '2026/5/29 05:00',
    periodEnd: '2026/5/30 05:00',
    creditedAt: '2026/5/30 05:00',
  },
];

export const MOCK_AGENT = {
  name: '人工介入员',
  phone: '18311925307',
  onDuty: true,
};

export const MOCK_CONVERSATIONS: MockConversation[] = [
  {
    id: '1',
    from: '小葵',
    to: 'QLC',
    platform: '微信',
    preview: '荒: 你不想理我就算了',
    time: '刚刚',
    unread: 1,
    avatarColor: '#7FB0D8',
    categoryId: 'lose-weight',
  },
  {
    id: '2',
    from: '小葵',
    to: '荒',
    platform: '抖音',
    preview: '荒: 你不想理我就算了',
    time: '昨天',
    unread: 1,
    avatarColor: '#E8A598',
    categoryId: 'coach-liu',
  },
  {
    id: '3',
    from: '小葵',
    to: '荒',
    platform: '微信',
    preview: '荒: 你不想理我就算了',
    time: '周三',
    unread: 2,
    avatarColor: '#B8A8E8',
    categoryId: 'noi',
  },
  {
    id: '4',
    from: '小葵',
    to: '荒',
    platform: '抖音',
    preview: '荒: 你不想理我就算了',
    time: '周三',
    unread: 1,
    avatarColor: '#E8A0B0',
    categoryId: 'lose-weight',
  },
  {
    id: '5',
    from: '小葵',
    to: '荒',
    platform: '微信',
    preview: '荒: 你不想理我就算了',
    time: '周三',
    unread: 1,
    avatarColor: '#E8D4A0',
    categoryId: 'coach-liu',
  },
];

export const MOCK_PERFORMANCE: MockPerformanceStats = {
  onlineDuration: '2 小时 45 分',
  replyCount: 0,
  salary: '¥102.95',
  deduction: '¥0',
  withdrawable: '¥102.95',
  withdrawn: '¥0',
};

export const MOCK_ACCOUNT = {
  phone: '17798573325',
};

export interface MockActorInfo {
  name: string;
  birthDate: string;
  city: string;
  profession: string;
  personality: string;
  remark: string;
  photos: string[];
}

const DEFAULT_ACTOR_INFO: MockActorInfo = {
  name: '熟透的桃桃',
  birthDate: '2002-01-07',
  city: '安徽省 合肥市 瑶海区',
  profession: '茶楼前台',
  personality: '外向、慢热、幽默、温柔、体贴、善解人意',
  remark: '喜欢健身，跑步',
  photos: [],
};

export function getMockActorInfo(_conversationId?: string): MockActorInfo {
  return DEFAULT_ACTOR_INFO;
}

// ── 标注员管理 ──────────────────────────────────────────────

export type AnnotatorStatus = 'online' | 'offline' | 'disabled';

export interface MockAnnotator {
  id: string;
  /** 后端 agent_id，拉取该客服会话列表用 */
  agentId?: string;
  name: string;
  phone: string;
  status: AnnotatorStatus;
  remark: string;
  /** 是否暂停接待新任务（overview 返回） */
  intakePaused?: boolean;
  /** 活跃会话上限（overview profile.max_active_cap） */
  maxActiveCap?: number | null;
  onlineDuration: string;
  replyCount: number;
  todaySalary: string;
  lastActiveAt: string;
}

export const MOCK_ANNOTATORS: MockAnnotator[] = [
  {
    id: 'a1',
    name: '林小雨',
    phone: '13800138001',
    status: 'online',
    remark: '夜班主力，擅长减肥类目',
    onlineDuration: '3 小时 12 分',
    replyCount: 28,
    todaySalary: '¥86.50',
    lastActiveAt: '刚刚',
  },
  {
    id: 'a2',
    name: '陈明远',
    phone: '13900139002',
    status: 'online',
    remark: '',
    onlineDuration: '1 小时 45 分',
    replyCount: 12,
    todaySalary: '¥42.00',
    lastActiveAt: '2 分钟前',
  },
  {
    id: 'a3',
    name: '赵婷婷',
    phone: '13700137003',
    status: 'offline',
    remark: '新人，需重点关注回复质量',
    onlineDuration: '0 分',
    replyCount: 0,
    todaySalary: '¥18.75',
    lastActiveAt: '1 小时前',
  },
  {
    id: 'a4',
    name: '王浩然',
    phone: '13600136004',
    status: 'offline',
    remark: '周末值班',
    onlineDuration: '0 分',
    replyCount: 0,
    todaySalary: '¥0',
    lastActiveAt: '昨天 22:10',
  },
  {
    id: 'a5',
    name: '刘思琪',
    phone: '13500135005',
    status: 'disabled',
    remark: '账号已停用',
    onlineDuration: '0 分',
    replyCount: 0,
    todaySalary: '¥0',
    lastActiveAt: '—',
  },
];

// ── 绩效核算 ──────────────────────────────────────────────

export type SettlementStatus = 'pending' | 'settled';

export interface MockSettlementItem {
  id: string;
  annotatorId: string;
  annotatorName: string;
  periodLabel: string;
  onlineDuration: string;
  replyCount: number;
  onlineSalary: number;
  replySalary: number;
  deduction: number;
  status: SettlementStatus;
}

export const MOCK_SETTLEMENT_ITEMS: MockSettlementItem[] = [
  {
    id: 's1',
    annotatorId: 'a1',
    annotatorName: '林小雨',
    periodLabel: '2026/6/17',
    onlineDuration: '3 小时 12 分',
    replyCount: 28,
    onlineSalary: 68.5,
    replySalary: 18.0,
    deduction: 0,
    status: 'pending',
  },
  {
    id: 's2',
    annotatorId: 'a2',
    annotatorName: '陈明远',
    periodLabel: '2026/6/17',
    onlineDuration: '1 小时 45 分',
    replyCount: 12,
    onlineSalary: 35.0,
    replySalary: 7.0,
    deduction: 0,
    status: 'pending',
  },
  {
    id: 's3',
    annotatorId: 'a3',
    annotatorName: '赵婷婷',
    periodLabel: '2026/6/17',
    onlineDuration: '2 小时 30 分',
    replyCount: 8,
    onlineSalary: 22.5,
    replySalary: 0,
    deduction: 3.75,
    status: 'pending',
  },
  {
    id: 's4',
    annotatorId: 'a1',
    annotatorName: '林小雨',
    periodLabel: '2026/6/16',
    onlineDuration: '5 小时 08 分',
    replyCount: 45,
    onlineSalary: 108.0,
    replySalary: 27.0,
    deduction: 10.0,
    status: 'settled',
  },
  {
    id: 's5',
    annotatorId: 'a2',
    annotatorName: '陈明远',
    periodLabel: '2026/6/16',
    onlineDuration: '4 小时 20 分',
    replyCount: 32,
    onlineSalary: 88.0,
    replySalary: 16.0,
    deduction: 0,
    status: 'settled',
  },
];
