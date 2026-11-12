// ============================================================
// Web 端全局 Alert Host（原生不渲染）
// 挂到应用内 overlay host（手机框内），避开撑满整个浏览器
// ============================================================
import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Platform, Pressable, StyleSheet, Text, View } from 'react-native';

import { useTheme } from '@/design/theme-context';
import { Tokens } from '@/design/tokens';
import {
  dismissAppAlert,
  subscribeAppAlert,
  type AppAlertButton,
  type AppAlertPayload,
} from '@/lib/app-alert';
import { getAppOverlayHost } from '@/lib/app-overlay-host';

export function AppAlertHost() {
  const theme = useTheme();
  const [payload, setPayload] = useState<AppAlertPayload | null>(null);

  useEffect(() => {
    if (Platform.OS !== 'web') return;
    return subscribeAppAlert(setPayload);
  }, []);

  if (Platform.OS !== 'web' || !payload || typeof document === 'undefined') {
    return null;
  }

  const handlePress = (btn: AppAlertButton) => {
    dismissAppAlert();
    queueMicrotask(() => {
      btn.onPress?.();
    });
  };

  const stacked = payload.buttons.length > 2;

  const node = (
    <View style={styles.host} pointerEvents="box-none">
      <Pressable style={styles.mask} onPress={dismissAppAlert}>
        <Pressable
          style={[styles.card, { backgroundColor: theme.surface, borderColor: theme.border }]}
          onPress={(e) => e.stopPropagation()}
        >
          <Text style={[styles.title, { color: theme.text }]}>{payload.title}</Text>
          {payload.message ? (
            <Text style={[styles.message, { color: theme.textSubtle }]}>{payload.message}</Text>
          ) : null}
          <View
            style={[
              styles.actions,
              stacked && styles.actionsStacked,
            ]}
          >
            {payload.buttons.map((btn, index) => {
              const label = btn.text || '确定';
              const isCancel = btn.style === 'cancel';
              const isDestructive = btn.style === 'destructive';
              const bg = isCancel
                ? theme.surface2
                : isDestructive
                  ? theme.danger
                  : theme.primary;
              const color = isCancel ? theme.textMuted : '#FFF';
              return (
                <Pressable
                  key={`${label}-${index}`}
                  style={[
                    styles.btn,
                    stacked
                      ? {
                          flexGrow: 0,
                          flexShrink: 0,
                          flexBasis: 'auto',
                          width: '100%',
                          height: 44,
                        }
                      : null,
                    { backgroundColor: bg },
                  ]}
                  onPress={() => handlePress(btn)}
                >
                  <Text style={[styles.btnText, { color }]} numberOfLines={1}>
                    {label}
                  </Text>
                </Pressable>
              );
            })}
          </View>
        </Pressable>
      </Pressable>
    </View>
  );

  return createPortal(node, getAppOverlayHost() ?? document.body);
}

const styles = StyleSheet.create({
  host: {
    ...StyleSheet.absoluteFillObject,
    zIndex: 100001,
  },
  mask: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(0,0,0,0.4)',
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: Tokens.spacing[8],
  },
  card: {
    width: '100%',
    maxWidth: 400,
    alignItems: 'stretch',
    borderRadius: Tokens.radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    padding: Tokens.spacing[5],
    gap: Tokens.spacing[3],
  },
  title: {
    fontSize: 17,
    fontWeight: '700',
  },
  message: {
    fontSize: 14,
    lineHeight: 20,
  },
  actions: {
    flexDirection: 'row',
    gap: Tokens.spacing[3],
    marginTop: Tokens.spacing[1],
  },
  actionsStacked: {
    flexDirection: 'column',
    alignSelf: 'stretch',
    width: '100%',
  },
  btn: {
    flexGrow: 1,
    flexShrink: 1,
    flexBasis: 'auto',
    height: 44,
    borderRadius: Tokens.radius.md,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 8,
  },
  btnText: {
    fontSize: 15,
    fontWeight: '600',
  },
});
