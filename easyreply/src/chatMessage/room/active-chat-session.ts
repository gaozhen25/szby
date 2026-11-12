// ============================================================
// 当前打开的聊天页会话（供根布局 / 在线提醒跨页面判断）
// 同时记 taskID 与 imConversationID：进房瞬间往往只有路由 id
// ============================================================

let activeImConversationID: string | null = null;
let activeTaskID: string | null = null;

export function setActiveChatImConversationID(id: string | null) {
  activeImConversationID = id?.trim() || null;
}

export function setActiveChatTaskID(id: string | null) {
  activeTaskID = id?.trim() || null;
}

export function clearActiveChatSession() {
  activeImConversationID = null;
  activeTaskID = null;
}

/** 是否正在看同一会话（imConversationID 或 taskID 任一命中） */
export function isActiveChatConversation(
  imConversationID?: string | null,
  taskID?: string | null,
): boolean {
  const im = imConversationID?.trim();
  if (im && activeImConversationID && im === activeImConversationID) return true;
  const task = taskID?.trim();
  if (task && activeTaskID && task === activeTaskID) return true;
  return false;
}
