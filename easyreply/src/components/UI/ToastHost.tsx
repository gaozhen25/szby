// ============================================================
// 全局 Toast Host
// - Web：挂到应用内 overlay host（手机框内）
// - 原生：绝对定位 View 叠在最上层
// - 位置：导航栏下方（与 CustomNavBar 高度对齐）
// ============================================================
import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Platform, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useTheme } from '@/design/theme-context';
import { Tokens } from '@/design/tokens';
import { getAppOverlayHost } from '@/lib/app-overlay-host';
import { subscribeAppToast, type AppToastPayload } from '@/lib/app-toast';

/** 与 CustomNavBar 内容区一致：paddingTop(8) + 行高(40) + paddingBottom(12) */
const NAV_BAR_CONTENT_HEIGHT =
  Tokens.spacing[2] + 40 + Tokens.spacing[3];

export function ToastHost() {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const [payload, setPayload] = useState<AppToastPayload | null>(null);

  useEffect(() => {
    return subscribeAppToast(setPayload);
  }, []);

  if (!payload) return null;

  const variant = payload.variant ?? 'default';
  const bg =
    variant === 'danger'
      ? theme.danger
      : variant === 'success'
        ? theme.success
        : theme.text;
  const node = (
    <View
      style={[
        styles.host,
        { paddingTop: insets.top + NAV_BAR_CONTENT_HEIGHT + Tokens.spacing[2] },
      ]}
      pointerEvents="box-none"
    >
      <View style={[styles.toast, { backgroundColor: bg }]}>
        <Text style={styles.message}>{payload.message}</Text>
      </View>
    </View>
  );

  if (Platform.OS === 'web' && typeof document !== 'undefined') {
    return createPortal(node, getAppOverlayHost() ?? document.body);
  }
  return node;
}

const styles = StyleSheet.create({
  host: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    alignItems: 'center',
    zIndex: 100002,
    paddingHorizontal: Tokens.spacing[4],
  },
  toast: {
    maxWidth: 460,
    width: '100%',
    borderRadius: Tokens.radius.md,
    paddingVertical: Tokens.spacing[3],
    paddingHorizontal: Tokens.spacing[4],
    shadowColor: '#1A1510',
    shadowOpacity: 0.16,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
    elevation: 4,
  },
  message: {
    color: '#FFF',
    fontSize: 14,
    lineHeight: 20,
    fontWeight: '600',
    textAlign: 'center',
  },
});
