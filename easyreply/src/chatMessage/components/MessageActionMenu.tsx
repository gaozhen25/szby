import { useEffect, useRef, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { CopyOutlined, SmileOutlined } from '@/ui/antd-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import {
  MESSAGE_ACTION_META,
  resolveMessageActions,
  type MessageActionMenuProps,
} from './MessageActionMenu.types';

export type {
  MessageActionId,
  MessageActionKind,
  MessageActionMenuAnchor,
  MessageActionMenuProps,
} from './MessageActionMenu.types';

const MENU_BG = 'rgba(60, 60, 60, 0.96)';
const ITEM_W = 44;
const ITEM_H = 46;
const CARET = 5;
const MENU_PAD_H = 4;
const MENU_PAD_V = 5;
const GAP = 2;

/** 手机端：微信风格图标网格 */
export function MessageActionMenu({
  visible,
  anchor,
  actions,
  kind = 'text',
  screenWidth,
  screenHeight: _screenHeight,
  onClose,
  onAction,
}: MessageActionMenuProps) {
  const insets = useSafeAreaInsets();
  const containerRef = useRef<View>(null);
  const [origin, setOrigin] = useState<{ x: number; y: number } | null>(null);
  const items = resolveMessageActions(kind, actions);

  useEffect(() => {
    if (!visible) {
      setOrigin(null);
      return;
    }
    const id = requestAnimationFrame(() => {
      containerRef.current?.measureInWindow((x, y) => {
        setOrigin({ x, y });
      });
    });
    return () => cancelAnimationFrame(id);
  }, [visible, anchor]);

  if (!visible || !anchor || items.length === 0) return null;

  const menuW = ITEM_W * items.length + MENU_PAD_H * 2;
  const menuH = ITEM_H + MENU_PAD_V * 2;

  const ready = origin != null;
  const localTop = ready ? anchor.top - origin.y : 0;
  const localBottom = ready ? anchor.bottom - origin.y : 0;
  const localCenterX = ready ? anchor.centerX - origin.x : 0;

  const placeAbove = localTop - menuH - CARET - GAP >= insets.top + 4;
  const menuTop = placeAbove
    ? localTop - menuH - CARET - GAP
    : localBottom + GAP;
  const menuLeft = Math.min(
    Math.max(localCenterX - menuW / 2, 8),
    Math.max(screenWidth - menuW - 8, 8),
  );
  const caretLeft = Math.min(
    Math.max(localCenterX - menuLeft - CARET, 10),
    menuW - 10 - CARET * 2,
  );

  return (
    <View ref={containerRef} style={styles.overlay} pointerEvents="box-none">
      <Pressable style={StyleSheet.absoluteFill} onPress={onClose} />
      {ready ? (
        <View
          style={[styles.wrap, { top: menuTop, left: menuLeft, width: menuW }]}
          pointerEvents="box-none"
        >
          {!placeAbove ? <View style={[styles.caretUp, { left: caretLeft }]} /> : null}
          <View style={styles.card}>
            {items.map((id) => {
              const meta = MESSAGE_ACTION_META[id];
              return (
                <Pressable
                  key={id}
                  style={({ pressed }) => [styles.item, pressed && { opacity: 0.55 }]}
                  onPress={() => onAction(id)}
                >
                  {id === 'copy' ? (
                    <CopyOutlined size={18} color="#FFF" />
                  ) : (
                    <SmileOutlined size={18} color="#FFF" />
                  )}
                  <Text style={styles.label}>{meta.label}</Text>
                </Pressable>
              );
            })}
          </View>
          {placeAbove ? <View style={[styles.caretDown, { left: caretLeft }]} /> : null}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  overlay: {
    ...StyleSheet.absoluteFillObject,
    zIndex: 100,
  },
  wrap: {
    position: 'absolute',
    alignItems: 'center',
    overflow: 'visible',
  },
  card: {
    backgroundColor: MENU_BG,
    borderRadius: 8,
    paddingHorizontal: MENU_PAD_H,
    paddingVertical: MENU_PAD_V,
    flexDirection: 'row',
    flexWrap: 'wrap',
  },
  item: {
    width: ITEM_W,
    height: ITEM_H,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 2,
  },
  label: { color: '#FFF', fontSize: 10, lineHeight: 12 },
  caretDown: {
    position: 'absolute',
    bottom: -CARET,
    width: 0,
    height: 0,
    borderLeftWidth: CARET,
    borderRightWidth: CARET,
    borderTopWidth: CARET,
    borderLeftColor: 'transparent',
    borderRightColor: 'transparent',
    borderTopColor: MENU_BG,
  },
  caretUp: {
    position: 'absolute',
    top: -CARET,
    width: 0,
    height: 0,
    borderLeftWidth: CARET,
    borderRightWidth: CARET,
    borderBottomWidth: CARET,
    borderLeftColor: 'transparent',
    borderRightColor: 'transparent',
    borderBottomColor: MENU_BG,
  },
});

export default MessageActionMenu;
