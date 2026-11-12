import { useEffect, useMemo, useRef, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { CopyOutlined, SmileOutlined } from '@/ui/web/antd-icons';
import {
  MESSAGE_ACTION_META,
  resolveMessageActions,
  type MessageActionMenuProps,
} from './MessageActionMenu.types';
import { webComponent } from '@/lib/web-component';
import { MessageActionMenu as NativeMessageActionMenu } from './MessageActionMenu.tsx';

export type {
  MessageActionId,
  MessageActionKind,
  MessageActionMenuAnchor,
  MessageActionMenuProps,
} from './MessageActionMenu.types';

const MENU_BG = 'rgba(60, 60, 60, 0.96)';
const ITEM_W = 52;
const ITEM_H = 48;
const MENU_PAD_H = 6;
const MENU_PAD_V = 6;
const GAP = 6;

/** Web：长按 / 右键弹出操作菜单 */
function WebMessageActionMenu({
  visible,
  anchor,
  actions,
  kind = 'text',
  screenWidth,
  screenHeight,
  onClose,
  onAction,
}: MessageActionMenuProps) {
  const items = useMemo(() => resolveMessageActions(kind, actions), [kind, actions]);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  const cardRef = useRef<View>(null);

  useEffect(() => {
    if (!visible || !anchor) {
      setPos(null);
      return;
    }

    const menuW = ITEM_W * Math.max(items.length, 1) + MENU_PAD_H * 2;
    const menuH = ITEM_H + MENU_PAD_V * 2;

    const preferX =
      typeof anchor.cursorX === 'number' ? anchor.cursorX : anchor.centerX;
    const preferY =
      typeof anchor.cursorY === 'number' ? anchor.cursorY : anchor.top;

    let left = preferX - menuW / 2;
    left = Math.min(Math.max(left, 8), Math.max(screenWidth - menuW - 8, 8));

    let top = preferY - menuH - GAP;
    if (top < 8) {
      top = (typeof anchor.cursorY === 'number' ? anchor.cursorY : anchor.bottom) + GAP;
    }
    if (top + menuH > screenHeight - 8) {
      top = Math.max(8, screenHeight - menuH - 8);
    }

    setPos({ left, top });
  }, [visible, anchor, items.length, screenWidth, screenHeight]);

  useEffect(() => {
    if (!visible || typeof document === 'undefined') return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    const onPointerDown = (e: PointerEvent) => {
      const target = e.target as HTMLElement | null;
      if (target?.closest('.qh-msg-action-menu')) return;
      onClose();
    };
    const timer = window.setTimeout(() => {
      document.addEventListener('pointerdown', onPointerDown, true);
      document.addEventListener('contextmenu', onPointerDown, true);
    }, 0);
    document.addEventListener('keydown', onKey);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onPointerDown, true);
      document.removeEventListener('contextmenu', onPointerDown, true);
    };
  }, [visible, onClose]);

  if (!visible || !anchor || !pos || items.length === 0) return null;

  return (
    <View style={styles.overlay} pointerEvents="box-none">
      <Pressable style={StyleSheet.absoluteFill} onPress={onClose} />
      <View
        ref={cardRef}
        style={[styles.card, { top: pos.top, left: pos.left }]}
        // @ts-expect-error RN Web
        className="qh-msg-action-menu"
        onContextMenu={(e: { preventDefault?: () => void }) => e?.preventDefault?.()}
      >
        {items.map((id) => {
          const meta = MESSAGE_ACTION_META[id];
          return (
            <Pressable
              key={id}
              style={({ pressed }) => [styles.item, pressed && { opacity: 0.55 }]}
              onPress={() => onAction(id)}
            >
              {id === 'copy' ? (
                <CopyOutlined style={{ fontSize: 18, color: '#FFF' }} />
              ) : (
                <SmileOutlined style={{ fontSize: 18, color: '#FFF' }} />
              )}
              <Text style={styles.label}>{meta.label}</Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  overlay: {
    ...StyleSheet.absoluteFillObject,
    zIndex: 100,
    position: 'fixed' as unknown as 'absolute',
  },
  card: {
    position: 'absolute',
    backgroundColor: MENU_BG,
    borderRadius: 8,
    paddingHorizontal: MENU_PAD_H,
    paddingVertical: MENU_PAD_V,
    flexDirection: 'row',
    // web-only shadow
    boxShadow: '0 8px 24px rgba(0,0,0,0.22)' as unknown as undefined,
  },
  item: {
    width: ITEM_W,
    height: ITEM_H,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 2,
  },
  label: { color: '#FFF', fontSize: 11, lineHeight: 14 },
});

export const MessageActionMenu = webComponent(WebMessageActionMenu, NativeMessageActionMenu);
export default MessageActionMenu;
