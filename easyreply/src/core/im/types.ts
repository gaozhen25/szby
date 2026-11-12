// ============================================================
// IM 公共类型定义
// ============================================================

export type ConnectionState = 'disconnected' | 'connecting' | 'connected' | 'reconnecting' | 'connection_timeout';
export type MessageStatus = 'sending' | 'sent' | 'failed';
export type MessageType = 'text' | 'image' | 'audio' | 'emoji' | 'system';
export type SenderRole = 'user' | 'agent' | 'system';
export type ReadStatus = 'unread' | 'read' | 'read_by_peer';

export type IMFrameType =
  // 既有 IM 协议帧
  | 'auth' | 'ping' | 'pong' | 'message' | 'ack' | 'read' | 'read_receipt' | 'sync' | 'sync_result' | 'error'
  // 联调网关帧（/ws/events）
  | 'connected' | 'send_message' | 'send_result' | 'echo_response'
  | 'ack_result' | 'resume' | 'resume_result' | 'publish' | 'publish_result';

export interface TextContent { text: string; }
export interface ImageContent { url: string; width?: number; height?: number; thumbnailUrl?: string; }
export interface AudioContent { url: string; duration: number; }
export interface EmojiContent { emojiId: string; fallback: string; }
export interface SystemContent { text: string; }

export type MessageContent = TextContent | ImageContent | AudioContent | EmojiContent | SystemContent;

export interface ChatMessage {
  clientMsgId: string; serverMsgId?: string; conversationId: string;
  senderId: string; senderRole: SenderRole; type: MessageType;
  content: MessageContent; status: MessageStatus; readStatus: ReadStatus;
  seq?: number; createdAt: number; extra?: Record<string, unknown>;
}

export interface Conversation {
  id: string; agentId?: string; agentName?: string; avatar?: string;
  lastMessagePreview?: string; lastMessageAt?: number; unreadCount: number; updatedAt: number;
}

export interface OutboxItem {
  clientMsgId: string; conversationId: string; frame: IMFrame;
  retryCount: number; nextRetryAt: number; createdAt: number;
}

export interface IMFrame {
  type: IMFrameType; requestId?: string; clientMsgId?: string; serverMsgId?: string;
  conversationId?: string; payload?: unknown; timestamp?: number;
  // ---- 联调网关字段 ----
  data?: unknown;          // 服务端结果/下发内容：send_result / ack_result / resume_result / publish_result / message
  ts?: number;             // pong 回包时间戳
  code?: string;           // error.code，例如 unsupported_message_type
  message?: string;        // error.message
  session_id?: string;     // connected 回包
  connection_id?: string;  // connected 回包
  ack_seq?: number;        // ack 上行：确认消费位点
  cursor?: string;         // ack 上行：游标
  from_seq?: number;       // resume 上行：起始序号
  limit?: number;          // resume 上行：拉取条数
  event_type?: string;     // publish 上行：事件类型
  delay_seconds?: number;  // echo_response 上行：延时下发秒数（顶层字段）
}

// ---- 联调网关服务端结果帧的 data 结构 ----
/** connected：建连后服务端首帧 */
export interface ConnectedFrameData { session_id: string; connection_id: string; }
/** send_result / echo_response 的确认 */
export interface SendResultData { session_id: string; received: boolean; queue_length: number; }
/** ack_result：位点确认结果 */
export interface AckResultData { session_id: string; ack_updated: boolean; ack_seq: number; }
/** resume_result：断线补拉结果 */
export interface ResumeResultData { session_id: string; session_found: boolean; need_full_sync: boolean; next_seq: number; events: unknown[]; }
/** publish_result：调试事件发布结果 */
export interface PublishResultData { session_id: string; seq: number; accepted: boolean; }

/** 网关下行消息（服务端 message 帧，供 UI 订阅展示） */
export interface GatewayInboundMessage { text: string; seq?: number; raw: unknown; receivedAt: number; }

export interface AckPayload { clientMsgId: string; serverMsgId: string; seq: number; conversationId: string; }
export interface ReadPayload { conversationId: string; readUpToSeq: number; }
export interface SyncPayload { conversationId: string; lastSeq: number; }
export interface SyncResultPayload { conversationId: string; messages: ChatMessage[]; hasMore: boolean; }

// ============================================================
// v2 网关：任务 / 服务端消息 / 下行业务事件
// 说明：v2 全链路无 seq，消息排序用 sendTime，去重用 serverMsgID
// ============================================================

/** 任务状态（0=待领取，1=已领取，2=处理中等，以服务端为准） */
export type TaskStatus = number;

/** 任务关联的会话快照 */
export interface IMTaskSession {
  sessionID: string;                      // 会话场次id
  actorPlatformID: string;                // 教练/我方平台id
  audiencePlatformID: string;             // 学员/对方平台id
  imConversationID: string;               // IM 会话id
  lastMessagePreview?: string;            // 最后一条消息预览
  status?: number;                        // 会话状态
  audiencePlatformNickname?: string;      // 学员昵称
  audiencePlatformFaceURL?: string;       // 学员头像
  actorPlatformNickname?: string;         // 教练昵称
  actorPlatformFaceURL?: string;          // 教练头像
}

/** 任务处理模式：human=人工，ai_assisted=AI 托管 */
export type TaskMode = 'human' | 'ai_assisted';

/**
 * 标注任务来源（ANNOTATION_TASK_SOURCE）
 * 下行 annotation_task_claimed.task.taskSource / 任务详情等同数字段
 * 暂仅本地记录枚举，业务功能后续再接
 */
export const AnnotationTaskSource = {
  /** 0 未知来源 */
  UNKNOWN: 0,
  /** 1 用户消息触发的普通人工任务 */
  USER_MESSAGE: 1,
  /** 2 AI 主动请求人工介入 */
  AI_REQUEST_HUMAN: 2,
  /** 3 AI 回复未通过采纳审核，转人工复审 */
  AI_NOT_ADOPTED: 3,
  /** 4 坐席或操作员主动转人工 */
  OPERATOR_TRANSFER: 4,
  /** 5 AI 监督或旁路场景产生的人工任务 */
  AI_SUPERVISION: 5,
  /** 6 定时主动触达产生的人工任务 */
  PROACTIVE_CONTACT: 6,
} as const;

export type AnnotationTaskSource =
  (typeof AnnotationTaskSource)[keyof typeof AnnotationTaskSource];

/** taskSource 数值 → 可读含义（调试/日志用） */
export const ANNOTATION_TASK_SOURCE_LABEL: Record<AnnotationTaskSource, string> = {
  [AnnotationTaskSource.UNKNOWN]: '未知来源',
  [AnnotationTaskSource.USER_MESSAGE]: '用户消息触发的普通人工任务',
  [AnnotationTaskSource.AI_REQUEST_HUMAN]: 'AI 主动请求人工介入',
  [AnnotationTaskSource.AI_NOT_ADOPTED]: 'AI 回复未通过采纳审核，转人工复审',
  [AnnotationTaskSource.OPERATOR_TRANSFER]: '坐席或操作员主动转人工',
  [AnnotationTaskSource.AI_SUPERVISION]: 'AI 监督或旁路场景产生的人工任务',
  [AnnotationTaskSource.PROACTIVE_CONTACT]: '定时主动触达产生的人工任务',
};

/** 任务实体（REST 列表/详情返回） */
export interface IMTask {
  taskID: string;                 // 任务id（核心主键：领取/发消息/动作都用它）
  sessionID: string;              // 会话场次id
  actorPlatformID: string;        // 我方角色平台id（可能为空，优先读 session）
  audiencePlatformID: string;     // 对方平台id（可能为空，优先读 session）
  imConversationID: string;       // IM 会话id（拉历史消息用）
  skillGroupID: string;           // 技能组（筛选/分类）
  /** 技能组标识：labor 表示劳务组（等同 AI 托管，见 isLaborSkillGroup） */
  skillGroup?: string;
  status: TaskStatus;             // 任务状态
  annotatorID?: string;           // 领取人（客服/标注员）id
  expectedAssigneeID?: string;    // 期望归属人id
  claimedAt?: number;             // 领取时间(ms)
  expireAt?: number;              // 领取过期时间(ms)
  createTime?: number;            // 创建时间(ms)
  updateTime?: number;            // 更新时间(ms)
  taskMode?: TaskMode;            // 处理模式：human / ai_assisted
  /** 任务来源（ANNOTATION_TASK_SOURCE），见 AnnotationTaskSource */
  taskSource?: AnnotationTaskSource | number;
  /** 任务原因摘要（如 AI 请求人工等场景） */
  reasonSummary?: string;
  /** AI 托管待人工复审上下文（tasks/detail / annotation_event eventType=8） */
  adoptionContext?: AdoptionContext;
  messages?: IMServerMessage[];   // claimed/list 返回的近期消息（用于取 lastMessage）
  lastMessage?: IMServerMessage;  // 最后一条消息（由 messages 末位派生，列表预览/时间来源）
  session?: IMTaskSession;        // 会话详情（昵称/头像等展示字段优先取这里）
}

/** AI 候选采纳状态：2=需人工复审（human_review_required）等 */
export type AdoptionStatus = number;

/** 人工对候选的动作：0=未处理，1=通过，2=拒绝 */
export type AdoptionHumanAction = 0 | 1 | 2;

/** 单条 AI 候选回复（待复审） */
export interface AdoptionCandidate {
  candidateID: string;
  index: number;
  contentType: number;
  originalContent: string;
  editedContent?: string;
  finalContent?: string;
  adoptionStatus?: AdoptionStatus;
  humanAction?: AdoptionHumanAction;
  adoptionReasonCode?: string;
  adoptionReasonSummary?: string;
}

/** AI 托管采纳/复审上下文 */
export interface AdoptionContext {
  executionTaskID?: string;
  aiAgentID?: string;
  adoptionID: string;
  adoptionStatus?: AdoptionStatus;
  reasonCode?: string;
  reasonSummary?: string;
  reasonDetails?: string;
  candidates?: AdoptionCandidate[];
}

/** 消息方向：0=学员进来，1=我方发出 */
export type MessageDirection = 0 | 1;

/** 服务端消息实体（无 seq，用 serverMsgID 去重、sendTime 排序） */
export interface IMServerMessage {
  serverMsgID: string;            // 消息唯一id（去重键）
  clientMsgID?: string;             // 客户端消息id
  conversationID?: string;          // 所属会话（部分接口不返回）
  senderPlatformID?: string;        // 旧字段：发送方平台id
  direction?: MessageDirection;     // 消息方向：0=进，1=出
  contentType?: number;             // 内容类型：101文本 / 102图片 / 103语音 / 104视频 / 105文件 / 109位置 / 114引用
  sendTime: number;               // 发送时间(ms)（排序键）
  content: string;                // 消息内容（可能是 JSON 字符串）
  ex?: string;                    // 扩展 JSON 字符串
  replySenderType?: string;
  replySenderID?: string;
  displaySenderType?: string;
}

/** 定时主动触达提醒（annotation_event eventType=5） */
export interface ProactiveActionHint {
  scheduledTaskID?: string;
  occurrenceKey?: string;
  taskName?: string;
  actionContent: string;
  actionPriority?: number;
  triggeredAt?: number;
}

/** 任务上下文（多数下行事件都会带） */
export interface IMTaskContext {
  taskID: string;                 // 任务id
  threadID?: string;              // 线程id
  sessionID?: string;             // 会话场次id
  imConversationID?: string;      // IM 会话id
  actorPlatformID?: string;
  audiencePlatformID?: string;
  actorPlatformNickname?: string;
  audiencePlatformNickname?: string;
  actorPlatformFaceURL?: string;
  audiencePlatformFaceURL?: string;
  /**
   * 触发本任务/复审的末条消息 serverMsgID。
   * ai_review_required：若有值须与会话 lastMessage.serverMsgID 一致，否则视为过时弃用。
   */
  lastTriggerMsgID?: string;
  proactiveActionHints?: ProactiveActionHint[];
}

/**
 * 动作类结果帧的 payload.type 集合
 * （对应 POST /api/app/actions/* 的入队回执之后，WS 下行最终业务结果）
 */
export type IMActionResultType =
  /** 客服上报转接给主管的结果 */
  | 'report_transfer_result'
  /** 主管进入任务线程、订阅旁观推送的结果 */
  | 'supervisor_enter_thread_result'
  /** 主管退出任务线程、取消旁观订阅的结果 */
  | 'supervisor_exit_thread_result'
  /** 主管接管任务成为当前 owner 的结果 */
  | 'supervisor_takeover_result'
  /** 主管将任务归还给原客服的结果 */
  | 'supervisor_return_to_agent_result'
  /** 系统强制切换任务归属到指定主管的结果 */
  | 'system_force_takeover_result'
  /** 客服释放任务回池的结果 */
  | 'release_task_result'
  /** 结束会话的结果 */
  | 'end_conversation_result'
  /** 标记任务完成（CompleteTask）的结果 */
  | 'complete_task_result'
  /** 切换任务处理模式（human/ai_assisted）的结果 */
  | 'set_task_mode_result'
  /** 客服确认已处理、暂停待处理超时倒计时的结果 */
  | 'ack_pending_result'
  /** 客服转派任务给另一客服的结果 */
  | 'transfer_task_result'
  /** 客服批量转派任务的汇总结果 */
  | 'transfer_task_batch_result';

/** 业务下行事件 payload.type 全集 */
export type IMGatewayEventType =
  /** 标注池消息事件（新消息 / 任务回收关闭等，用于渲染气泡与刷新列表） */
  | 'annotation_event'
  /** AI 候选需人工复审（等价 annotation_event eventType=8） */
  | 'ai_review_required'
  /** 新任务被当前账号认领（含 task.taskSource） */
  | 'annotation_task_claimed'
  /** 客服上报转接后推送给主管的通知 */
  | 'transfer_reported'
  /** 任务所有权变更（锁定/解锁输入框的主要依据） */
  | 'ownership_changed'
  /** 发送消息的最终业务结果（≠ send_result 入队回执） */
  | 'submit_result'
  /** 动作类接口的最终业务结果 */
  | IMActionResultType;

/** annotation_event：标注池消息事件（渲染气泡/状态） */
export interface IMAnnotationEventPayload {
  type: 'annotation_event';
  task_context: IMTaskContext;
  event: {
    eventID: string;              // 事件id
    taskID: string;               // 任务id
    sessionID?: string;           // 场次id
    annotatorID?: string;         // 标注员id
    eventType?: number;           // 1=新消息；2/3=任务从当前账号移除；5=定时主动触达提醒；8=AI 候选需人工复审
    eventTime?: number;           // 事件时间(ms)
    content?: string;             // 事件文本
    message: IMServerMessage;     // 真正用于渲染气泡的消息体
    /** eventType=8 时携带待复审候选 */
    adoptionContext?: AdoptionContext;
    /** eventType=5 时携带主动触达提醒 */
    proactiveActionHints?: ProactiveActionHint[];
  };
}

/** annotation_task_claimed：新任务被当前账号认领 */
export interface IMAnnotationTaskClaimedPayload {
  type: 'annotation_task_claimed';
  task_context: IMTaskContext;
  /** 认领任务快照（含 taskSource / taskMode 等） */
  task?: IMTask;
}

/**
 * ai_review_required：AI 候选需人工复审
 * 结构与 annotation_event(eventType=8) 类似，独立 type 便于订阅
 */
export interface IMAiReviewRequiredPayload {
  type: 'ai_review_required';
  task_context: IMTaskContext;
  event: {
    eventID: string;
    taskID: string;
    sessionID?: string;
    annotatorID?: string;
    eventType?: number;
    eventTime?: number;
    content?: string;
    message?: IMServerMessage;
    adoptionContext?: AdoptionContext;
  };
}

/** transfer_reported：客服上报转接后推送给主管 */
export interface IMTransferReportedPayload {
  type: 'transfer_reported';
  taskID: string;                 // 任务id
  task_context: IMTaskContext;    // 任务上下文
  fromAgentId: string;            // 上报客服id
  targetRole: string;            // 目标角色（如 supervisor）
  reason?: string;                // 转接原因（可选，不传视为空字符串，原样透传）
}

/** ownership_changed：所有权变化（锁定/解锁输入框的唯一依据） */
export interface IMOwnershipChangedPayload {
  type: 'ownership_changed';
  taskID: string;                 // 任务id
  task_context: IMTaskContext;    // 任务上下文
  reason: string;                 // 变更原因：release_task / supervisor_takeover / return_to_agent / return_to_agent_original_offline / manual_transfer
  currentAssigneeId: string;      // 当前持有人id（""=无人）
  currentAssigneeRole: string;    // 当前持有人角色：agent / supervisor / none
  previousAssigneeId?: string;    // 上一持有人id
  previousAssigneeRole?: string;  // 上一持有人角色（部分场景可能没有）
}

/** submit_result：send_message 的最终业务结果（≠ send_result 入队回执） */
export interface IMSubmitResultPayload {
  type: 'submit_result';
  ok: boolean;                    // 是否成功
  taskID: string;                 // 任务id
  task_context?: IMTaskContext;   // 任务上下文
  serverMsgID?: string;           // 成功时返回的消息id
  /** 若服务端回显上行 clientMsgID，优先用于配对乐观气泡 */
  clientMsgID?: string;
  currentAssigneeId?: string;     // 部分失败场景返回
  error?: string;                 // 失败原因
}

/** 动作类结果帧（report_transfer / supervisor_* / release / end / system_force_takeover） */
export interface IMActionResultPayload {
  type: IMActionResultType;
  ok: boolean;                    // 是否成功
  taskID?: string;                // 任务id（部分失败场景可能没有）
  task_context?: IMTaskContext;   // 任务上下文
  error?: string;                 // 失败原因
  status?: string;                // release/end 等返回：open / ended ...
  currentAssigneeId?: string;     // 接管/归还后当前持有人
  currentAssigneeRole?: string;   // 接管/归还后当前持有人角色
  supervisorId?: string;          // report_transfer_result：接手主管
  supervisorOnline?: boolean;     // report_transfer_result：主管是否在线
  expectedSupervisorID?: string;  // system_force_takeover 离线失败时
  reason?: string;                // report_transfer_result / system_force_takeover 等：原因（透传）
  // complete_task_result 扩展字段（服务端可能下发）
  completedAt?: number;
  downstreamOK?: boolean;
  downstreamError?: string;
  // set_task_mode_result 扩展字段
  taskMode?: TaskMode;
}

/** 业务下行事件联合类型（内层 payload） */
export type IMGatewayEvent =
  | IMAnnotationEventPayload
  | IMAiReviewRequiredPayload
  | IMAnnotationTaskClaimedPayload
  | IMTransferReportedPayload
  | IMOwnershipChangedPayload
  | IMSubmitResultPayload
  | IMActionResultPayload;

export interface IMConnectionOptions {
  heartbeatInterval?: number;
  heartbeatTimeout?: number;
  reconnectBaseDelay?: number;
  reconnectMaxDelay?: number;
  /**
   * 自动重连硬上限。
   * 0 = 不设硬上限（默认，由保活策略 softUiTimeoutAttempts 控制 UI 超时并继续慢重试）。
   */
  maxReconnectAttempts?: number;
  ackTimeout?: number;
  /** 握手成功后等待服务端 connected 帧的最长毫秒数，超时则断开并重连 */
  connectedConfirmTimeout?: number;
}

export type IMConnectionEvent =
  | { type: 'state_change'; state: ConnectionState }
  | { type: 'frame'; frame: IMFrame }
  | { type: 'error'; error: Error }
  | { type: 'network_change'; online: boolean };

export type IMConnectionListener = (event: IMConnectionEvent) => void;
