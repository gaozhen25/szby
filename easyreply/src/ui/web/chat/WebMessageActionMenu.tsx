import { Button, Dropdown, Flex } from 'antd';
import { CopyOutlined, SmileOutlined } from '@/ui/web/antd-icons';
import type { MenuProps } from 'antd';
import { useEffect, useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import type {
  MessageActionId,
  MessageActionKind,
  MessageActionMenuAnchor,
} from '@/chatMessage/components/MessageActionMenu.types';

function actionsForKind(kind: MessageActionKind): MessageActionId[] {
  if (kind === 'sticker') return ['add_sticker'];
  if (kind === 'image') return ['copy', 'add_sticker'];
  return ['copy'];
}

const ACTION_META: Record<MessageActionId, { icon: ReactNode; label: string }> = {
  copy: { icon: <CopyOutlined />, label: '复制' },
  add_sticker: { icon: <SmileOutlined />, label: '添加表情' },
};

export function WebMessageActionMenu({
  visible,
  kind,
  anchor,
  onClose,
  onAction,
}: {
  visible: boolean;
  kind: MessageActionKind;
  anchor: MessageActionMenuAnchor | null;
  onClose: () => void;
  onAction: (id: MessageActionId) => void;
}) {
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!visible || typeof document === 'undefined') return;

    const close = () => onCloseRef.current();
    const onPointerDown = (e: Event) => {
      const target = e.target as HTMLElement | null;
      if (target?.closest('.qh-msg-action-menu, .ant-dropdown')) return;
      close();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close();
    };

    const timer = window.setTimeout(() => {
      document.addEventListener('pointerdown', onPointerDown, true);
      document.addEventListener('contextmenu', onPointerDown, true);
    }, 0);
    document.addEventListener('keydown', onKey);
    document.addEventListener('scroll', close, true);

    return () => {
      window.clearTimeout(timer);
      document.removeEventListener('pointerdown', onPointerDown, true);
      document.removeEventListener('contextmenu', onPointerDown, true);
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('scroll', close, true);
    };
  }, [visible]);

  if (!visible || !anchor || typeof document === 'undefined') return null;

  const left = anchor.cursorX ?? anchor.centerX;
  const top = anchor.cursorY ?? anchor.bottom;

  const items: MenuProps['items'] = actionsForKind(kind).map((id) => ({
    key: id,
    icon: ACTION_META[id].icon,
    label: ACTION_META[id].label,
  }));

  return createPortal(
    <>
      <Flex
        className="qh-msg-action-mask"
        onClick={onClose}
        onContextMenu={(e) => {
          e.preventDefault();
          onClose();
        }}
        style={{ position: 'fixed', inset: 0, zIndex: 1049 }}
      />
      <Dropdown
        open
        trigger={[]}
        placement="bottomLeft"
        getPopupContainer={() => document.body}
        overlayClassName="qh-msg-action-menu"
        overlayStyle={{ zIndex: 1050 }}
        onOpenChange={(open) => {
          if (!open) onClose();
        }}
        menu={{
          items,
          onClick: ({ key }) => onAction(key as MessageActionId),
        }}
      >
        <Button
          type="text"
          aria-hidden
          tabIndex={-1}
          style={{
            position: 'fixed',
            left,
            top,
            width: 1,
            height: 1,
            minWidth: 1,
            padding: 0,
            pointerEvents: 'none',
            opacity: 0,
            zIndex: 1050,
          }}
        />
      </Dropdown>
    </>,
    document.body,
  );
}
