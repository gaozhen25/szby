import { useEffect, useRef } from 'react';
import {
  Animated,
  Easing,
  Platform,
  StyleSheet,
  useWindowDimensions,
  View,
  type ViewProps,
} from 'react-native';

import { useTheme } from '@/design/theme-context';
import { registerAppOverlayHost } from '@/lib/app-overlay-host';

/** 桌面宽屏时居中手机框宽度 */
const PHONE_WIDTH = 430;
/** 小于此宽度时取消外壳，真机浏览器全宽 */
const SHELL_MIN_VIEWPORT = 520;

function AppOverlayHost() {
  if (Platform.OS !== 'web') return null;
  return (
    <View
      ref={(node) => registerAppOverlayHost(node)}
      pointerEvents="box-none"
      style={styles.overlayHost}
    />
  );
}

function ensureWebViewportCss() {
  if (typeof document === 'undefined') return;
  const id = 'qh-web-phone-shell-css';
  if (document.getElementById(id)) return;
  const style = document.createElement('style');
  style.id = id;
  style.textContent = `
    html, body, #root {
      height: 100%;
      margin: 0;
      overflow: hidden;
      background: #E8EDE9;
    }
    #root > div {
      height: 100%;
    }
  `;
  document.head.appendChild(style);
}

function DriftOrb({
  size,
  color,
  opacity,
  initial,
  drift,
  duration,
}: {
  size: number;
  color: string;
  opacity: number;
  initial: { x: number; y: number };
  drift: { x: number; y: number };
  duration: number;
}) {
  const anim = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(anim, {
          toValue: 1,
          duration,
          easing: Easing.inOut(Easing.sin),
          useNativeDriver: false,
        }),
        Animated.timing(anim, {
          toValue: 0,
          duration,
          easing: Easing.inOut(Easing.sin),
          useNativeDriver: false,
        }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [anim, duration]);

  const translateX = anim.interpolate({
    inputRange: [0, 1],
    outputRange: [initial.x, initial.x + drift.x],
  });
  const translateY = anim.interpolate({
    inputRange: [0, 1],
    outputRange: [initial.y, initial.y + drift.y],
  });

  return (
    <Animated.View
      pointerEvents="none"
      style={{
        position: 'absolute',
        width: size,
        height: size,
        borderRadius: size / 2,
        backgroundColor: color,
        opacity,
        transform: [{ translateX }, { translateY }],
      }}
    />
  );
}

/**
 * Web 桌面：居中手机框 + 两侧氛围背景动画。
 * 窄屏 / 原生：直接透传 children。
 */
export function WebPhoneShell({ children, style, ...rest }: ViewProps) {
  const theme = useTheme();
  const { width, height } = useWindowDimensions();
  const useShell = Platform.OS === 'web' && width >= SHELL_MIN_VIEWPORT;

  useEffect(() => {
    if (Platform.OS === 'web') ensureWebViewportCss();
  }, []);

  if (!useShell) {
    return (
      <View style={[styles.fill, style]} {...rest}>
        {children}
        <AppOverlayHost />
      </View>
    );
  }

  return (
    <View style={[styles.viewport, { backgroundColor: '#E8EDE9' }, style]} {...rest}>
      <View style={styles.backdrop} pointerEvents="none">
        <DriftOrb
          size={320}
          color={theme.primarySoft}
          opacity={0.85}
          initial={{ x: -40, y: 40 }}
          drift={{ x: 48, y: 36 }}
          duration={9000}
        />
        <DriftOrb
          size={280}
          color={theme.wash1}
          opacity={0.7}
          initial={{ x: width - 260, y: 120 }}
          drift={{ x: -56, y: 40 }}
          duration={11000}
        />
        <DriftOrb
          size={220}
          color={theme.wash2}
          opacity={0.55}
          initial={{ x: 80, y: Math.max(height - 280, 200) }}
          drift={{ x: 36, y: -48 }}
          duration={10000}
        />
        <DriftOrb
          size={180}
          color={theme.primary}
          opacity={0.12}
          initial={{ x: width - 220, y: Math.max(height - 220, 320) }}
          drift={{ x: -40, y: -28 }}
          duration={12000}
        />
      </View>

      <View
        style={[
          styles.phone,
          {
            backgroundColor: theme.bg,
            maxWidth: PHONE_WIDTH,
            borderColor: 'rgba(26,21,16,0.08)',
          },
        ]}
      >
        <View style={styles.phoneInner}>{children}</View>
        <AppOverlayHost />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  fill: {
    flex: 1,
    position: 'relative',
    ...(Platform.OS === 'web'
      ? ({ height: '100%', minHeight: '100%' } as object)
      : null),
  },
  viewport: {
    flex: 1,
    width: '100%',
    height: '100%' as unknown as number,
    minHeight: '100%' as unknown as number,
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
    paddingVertical: 16,
  },
  backdrop: {
    ...StyleSheet.absoluteFillObject,
    overflow: 'hidden',
  },
  phone: {
    width: '100%',
    flex: 1,
    maxHeight: '100%' as unknown as number,
    borderRadius: 28,
    overflow: 'hidden',
    position: 'relative',
    borderWidth: StyleSheet.hairlineWidth,
    ...(Platform.OS === 'web'
      ? ({
          boxShadow: '0 28px 80px rgba(26, 21, 16, 0.18), 0 0 0 1px rgba(26,21,16,0.04)',
        } as object)
      : {
          shadowColor: '#1A1510',
          shadowOpacity: 0.18,
          shadowRadius: 40,
          shadowOffset: { width: 0, height: 20 },
          elevation: 12,
        }),
  },
  phoneInner: {
    flex: 1,
    width: '100%',
    height: '100%' as unknown as number,
    overflow: 'hidden',
  },
  overlayHost: {
    ...StyleSheet.absoluteFillObject,
    zIndex: 99990,
  },
});
