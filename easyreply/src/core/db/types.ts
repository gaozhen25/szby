// ============================================================
// 本地结构化存储：会话表 schema 与仓储接口
// - Native：expo-sqlite（conversation-repo.ts）
// - Web：Dexie / IndexedDB（conversation-repo.web.ts）
//
// 选型说明：Web 端不用 expo-sqlite，因其依赖 SharedArrayBuffer，
// 需要 COOP/COEP 跨域隔离；require-corp 会打挂企微头像等跨域图片，
// 而 credentialless Safari 至今不支持。
// ============================================================

/**
 * 会话表一行。
 * 走「索引列 + data JSON」模式：查询/排序用得上的字段拆成列，
 * 其余整体存 data，避免 MockConversation 增删字段就要改表。
 */
export type ConversationRow = {
  /** 租户 + 角色 + 客服 的隔离键 */
  scopeKey: string;
  /** 主键（与 scopeKey 组成复合主键）：taskID，缺失时回退 im:<imConversationID> */
  taskID: string;
  imConversationID: string;
  /** 列表排序用（lastMessage.sendTime），缺失为 0 */
  sortTime: number;
  /** 0/1，供后续「只加载活跃会话」等分片查询 */
  inactive: number;
  updatedAt: number;
  /** 序列化后的 MockConversation */
  data: string;
};

export type ConversationDiff = {
  upserts: ConversationRow[];
  /** 待删除行的 taskID（即 ConversationRow.taskID） */
  deleteTaskIDs: string[];
};

/**
 * 会话仓储。实现层只负责存取，不做业务合并；
 * 失败直接抛出，由调用方决定降级策略。
 */
export interface ConversationRepo {
  loadScope(scopeKey: string): Promise<ConversationRow[]>;
  applyDiff(scopeKey: string, diff: ConversationDiff): Promise<void>;
  clearScope(scopeKey: string): Promise<void>;
}
