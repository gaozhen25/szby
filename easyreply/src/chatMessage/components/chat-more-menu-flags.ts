/** TODO: 临时隐藏「开启/关闭 AI 托管」更多菜单入口；恢复时改为 true（Web / 原生共用） */
export const SHOW_AGENT_TASK_MODE_IN_MORE_MENU = false;

/** 聊天页右上角「...」更多菜单文案（Web / 原生共用） */
export const CHAT_MORE_MENU_LABELS = {
  ack: '已处理',
  ackSubmitting: '处理中…',
  report: '上报问题',
  end: '结束会话',
  takeover: '接管会话',
  transfer: '转移会话',
  complete: '完成任务',
  return: '归还客服',
  cancel: '取消',
} as const;
