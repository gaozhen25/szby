import { useEffect, useRef } from 'react';
import {
  Animated,
  Easing,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { CloudOutlined, ExclamationCircleOutlined, SyncOutlined } from '@/ui/antd-icons';

import { useTheme } from '@/design/theme-context';
import { Tokens } from '@/design/tokens';

export type ConnectionBannerMode = 'offline' | 'connecting' | 'reconnecting' | 'timeout';

const BANNER_COPY: Record<ConnectionBannerMode, { title: string; subtitle: string }> = {
  offline: { title: '网络已断开', subtitle: '请连接网络' },
  connecting: { title: '正在连接中…', subtitle: '正在尝试接入会话服务' },
  reconnecting: { title: '正在重连中…', subtitle: '网络环境不稳定，正在努力连接' },
  timeout: { title: '连接超时', subtitle: '请检查网络环境' },
};

const PULSE_PERIOD = 1400;
const PULSE_PAUSE = 300;

function RetryRippleButton({
  accent,
  backgroundColor,
  onPress,
}: {
  accent: string;
  backgroundColor: string;
  onPress: () => void;
}) {
  const pulse = useRef(new Animated.Value(0)).current;
  const btnScale = useRef(new Animated.Value(1)).current;

  useEffect(() => {
    const ringAnim = Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, {
          toValue: 1,
          duration: PULSE_PERIOD,
          easing: Easing.out(Easing.cubic),
          useNativeDriver: true,
        }),
        Animated.timing(pulse, { toValue: 0, duration: 0, useNativeDriver: true }),
        Animated.delay(PULSE_PAUSE),
      ]),
    );
    const breatheAnim = Animated.loop(
      Animated.sequence([
        Animated.timing(btnScale, {
          toValue: 1.04,
          duration: (PULSE_PERIOD + PULSE_PAUSE) / 2,
          easing: Easing.inOut(Easing.cubic),
          useNativeDriver: true,
        }),
        Animated.timing(btnScale, {
          toValue: 1,
          duration: (PULSE_PERIOD + PULSE_PAUSE) / 2,
          easing: Easing.inOut(Easing.cubic),
          useNativeDriver: true,
        }),
      ]),
    );
    ringAnim.start();
    breatheAnim.start();
    return () => {
      ringAnim.stop();
      breatheAnim.stop();
      pulse.setValue(0);
      btnScale.setValue(1);
    };
  }, [btnScale, pulse]);

  const ringScale = pulse.interpolate({ inputRange: [0, 1], outputRange: [1, 1.7] });
  const ringOpacity = pulse.interpolate({ inputRange: [0, 0.12, 0.55, 1], outputRange: [0, 0.65, 0.2, 0] });

  return (
    <View style={styles.retryRippleWrap}>
      <Animated.View
        pointerEvents="none"
        style={[
          styles.retryPulseRing,
          { borderColor: accent, opacity: ringOpacity, transform: [{ scale: ringScale }] },
        ]}
      />
      <Animated.View style={{ transform: [{ scale: btnScale }], zIndex: 1 }}>
        <Pressable
          style={({ pressed }) => [
            styles.connectionBannerRetry,
            { borderColor: accent, backgroundColor },
            pressed && styles.connectionBannerRetryPressed,
          ]}
          onPress={onPress}
          accessibilityRole="button"
          accessibilityLabel="重试连接"
        >
          <Text style={[styles.connectionBannerRetryText, { color: accent }]}>重试</Text>
        </Pressable>
      </Animated.View>
    </View>
  );
}

export function ConnectionBanner({
  mode,
  onRetry,
}: {
  mode: ConnectionBannerMode;
  onRetry?: () => void;
}) {
  const theme = useTheme();
  const pulse = useRef(new Animated.Value(1)).current;
  const spin = useRef(new Animated.Value(0)).current;
  const offlinePulse = useRef(new Animated.Value(1)).current;
  const offlineShake = useRef(new Animated.Value(0)).current;
  const offlineSignal = useRef(new Animated.Value(0)).current;

  const isOffline = mode === 'offline';
  const isTimeout = mode === 'timeout';
  const isConnecting = mode === 'connecting' || mode === 'reconnecting';
  const accent = isOffline ? theme.danger : isTimeout ? theme.warning : theme.info;
  const softBg = isOffline ? theme.dangerSoft : isTimeout ? theme.warningSoft : theme.infoSoft;
  const { title, subtitle } = BANNER_COPY[mode];

  useEffect(() => {
    if (!isConnecting) return;
    const dotAnim = Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, { toValue: 0.4, duration: 700, useNativeDriver: true }),
        Animated.timing(pulse, { toValue: 1, duration: 700, useNativeDriver: true }),
      ]),
    );
    const spinAnim = Animated.loop(
      Animated.sequence([
        Animated.timing(spin, {
          toValue: 1,
          duration: 1200,
          useNativeDriver: true,
          easing: Easing.linear,
        }),
        Animated.timing(spin, { toValue: 0, duration: 0, useNativeDriver: true }),
      ]),
    );
    dotAnim.start();
    spinAnim.start();
    return () => {
      dotAnim.stop();
      spinAnim.stop();
    };
  }, [isConnecting, pulse, spin]);

  useEffect(() => {
    if (!isOffline) {
      offlinePulse.setValue(1);
      offlineShake.setValue(0);
      offlineSignal.setValue(0);
      return;
    }
    const breathe = Animated.loop(
      Animated.sequence([
        Animated.timing(offlinePulse, {
          toValue: 0.5,
          duration: 1000,
          easing: Easing.inOut(Easing.ease),
          useNativeDriver: true,
        }),
        Animated.timing(offlinePulse, {
          toValue: 1,
          duration: 1000,
          easing: Easing.inOut(Easing.ease),
          useNativeDriver: true,
        }),
      ]),
    );
    const shake = Animated.loop(
      Animated.sequence([
        Animated.delay(600),
        Animated.timing(offlineShake, { toValue: 1, duration: 60, useNativeDriver: true }),
        Animated.timing(offlineShake, { toValue: -1, duration: 60, useNativeDriver: true }),
        Animated.timing(offlineShake, { toValue: 0.7, duration: 50, useNativeDriver: true }),
        Animated.timing(offlineShake, { toValue: -0.7, duration: 50, useNativeDriver: true }),
        Animated.timing(offlineShake, { toValue: 0, duration: 50, useNativeDriver: true }),
        Animated.delay(1800),
      ]),
    );
    const signal = Animated.loop(
      Animated.sequence([
        Animated.timing(offlineSignal, {
          toValue: 1,
          duration: 1400,
          easing: Easing.out(Easing.ease),
          useNativeDriver: true,
        }),
        Animated.timing(offlineSignal, { toValue: 0, duration: 0, useNativeDriver: true }),
        Animated.delay(600),
      ]),
    );
    breathe.start();
    shake.start();
    signal.start();
    return () => {
      breathe.stop();
      shake.stop();
      signal.stop();
    };
  }, [isOffline, offlinePulse, offlineShake, offlineSignal]);

  const offlineShakeX = offlineShake.interpolate({ inputRange: [-1, 1], outputRange: [-3, 3] });
  const accentBarOpacity = offlinePulse.interpolate({ inputRange: [0.5, 1], outputRange: [0.45, 1] });
  const signalScale = offlineSignal.interpolate({ inputRange: [0, 1], outputRange: [1, 2.2] });
  const signalOpacity = offlineSignal.interpolate({ inputRange: [0, 0.2, 1], outputRange: [0, 0.35, 0] });

  return (
    <View
      style={[styles.connectionBanner, { backgroundColor: softBg, borderColor: accent }, Tokens.shadow.card]}
      accessibilityRole="alert"
    >
      {isOffline ? (
        <Animated.View style={[styles.connectionBannerAccent, { backgroundColor: accent, opacity: accentBarOpacity }]} />
      ) : (
        <View style={[styles.connectionBannerAccent, { backgroundColor: accent }]} />
      )}
      <View style={[styles.connectionBannerIconWrap, { backgroundColor: theme.surface, borderColor: accent, overflow: 'hidden' }]}>
        {isOffline ? (
          <>
            <Animated.View
              pointerEvents="none"
              style={[
                styles.offlineSignalRing,
                { borderColor: accent, opacity: signalOpacity, transform: [{ scale: signalScale }] },
              ]}
            />
            <Animated.View
              style={{
                opacity: offlinePulse,
                transform: [{ translateX: offlineShakeX }],
              }}
            >
              <CloudOutlined size={20} color={accent} />
            </Animated.View>
          </>
        ) : isTimeout ? (
          <ExclamationCircleOutlined size={20} color={accent} />
        ) : (
          <Animated.View style={{
            transform: [{
              rotate: spin.interpolate({ inputRange: [0, 1], outputRange: ['0deg', '360deg'] }),
            }],
          }}>
            <SyncOutlined size={20} color={accent} />
          </Animated.View>
        )}
      </View>
      <View style={styles.connectionBannerBody}>
        <Text style={[styles.connectionBannerTitle, { color: accent }]}>{title}</Text>
        <Text style={[styles.connectionBannerSubtitle, { color: theme.textMuted }]}>{subtitle}</Text>
      </View>
      {isTimeout && onRetry ? (
        <RetryRippleButton accent={accent} backgroundColor={theme.surface} onPress={onRetry} />
      ) : isOffline ? (
        <Animated.View style={[styles.connectionBannerDot, { backgroundColor: accent, opacity: offlinePulse }]} />
      ) : isConnecting ? (
        <Animated.View style={[styles.connectionBannerDot, { backgroundColor: accent, opacity: pulse }]} />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  connectionBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Tokens.spacing[3],
    paddingVertical: Tokens.spacing[3],
    paddingRight: Tokens.spacing[4],
    borderRadius: Tokens.radius.md,
    borderWidth: 1,
    marginBottom: Tokens.spacing[3],
    overflow: 'visible',
  },
  connectionBannerAccent: {
    width: 4,
    alignSelf: 'stretch',
  },
  connectionBannerIconWrap: {
    width: 40,
    height: 40,
    borderRadius: Tokens.radius.sm,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
    marginLeft: Tokens.spacing[3],
  },
  offlineSignalRing: {
    ...StyleSheet.absoluteFillObject,
    borderRadius: Tokens.radius.sm,
    borderWidth: 1.5,
  },
  connectionBannerBody: {
    flex: 1,
    gap: 2,
  },
  connectionBannerTitle: {
    fontSize: 15,
    lineHeight: 20,
    fontWeight: '700',
    letterSpacing: -0.2,
  },
  connectionBannerSubtitle: {
    fontSize: 13,
    lineHeight: 18,
  },
  connectionBannerDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  retryRippleWrap: {
    width: 68,
    height: 36,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: Tokens.spacing[1],
  },
  retryPulseRing: {
    ...StyleSheet.absoluteFillObject,
    borderRadius: Tokens.radius.sm,
    borderWidth: 1.5,
  },
  connectionBannerRetry: {
    paddingHorizontal: 14,
    paddingVertical: 7,
    borderRadius: Tokens.radius.sm,
    borderWidth: 1,
    minWidth: 52,
    alignItems: 'center',
  },
  connectionBannerRetryPressed: {
    opacity: 0.88,
  },
  connectionBannerRetryText: {
    fontSize: 13,
    fontWeight: '600',
  },
});

export default ConnectionBanner;
