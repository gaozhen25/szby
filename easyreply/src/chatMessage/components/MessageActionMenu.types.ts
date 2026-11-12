export type MessageActionMenuAnchor = {
  /** 气泡顶边（窗口坐标） */
  top: number;
  /** 气泡底边（窗口坐标） */
  bottom: number;
  /** 气泡水平中心（窗口坐标） */
  centerX: number;
  /** 右键时用鼠标坐标（Web）；手机端忽略 */
  cursorX?: number;
  cursorY?: number;
};

export type MessageActionId = 'copy' | 'add_sticker';

export type MessageActionKind = 'text' | 'image' | 'sticker';

export type MessageActionMenuProps = {
  visible: boolean;
  anchor: MessageActionMenuAnchor | null;
  /** 当前菜单可用操作；默认按 kind 推导 */
  actions?: MessageActionId[];
  kind?: MessageActionKind;
  screenWidth: number;
  screenHeight: number;
  onClose: () => void;
  onAction: (id: MessageActionId) => void;
};

export function resolveMessageActions(
  kind: MessageActionKind,
  actions?: MessageActionId[],
): MessageActionId[] {
  if (actions?.length) return actions;
  if (kind === 'sticker') return ['add_sticker'];
  return ['copy'];
}

export const MESSAGE_ACTION_META: Record<MessageActionId, { label: string }> = {
  copy: { label: '复制' },
  add_sticker: { label: '添加' },
};
