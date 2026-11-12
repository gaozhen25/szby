import { useEffect, useRef } from 'react';
import { Animated, StyleSheet, Text, View } from 'react-native';
import { InAppModal } from '@/components/UI/InAppModal';

export type VoiceRecordGestureZone = 'none' | 'cancel' | 'convert' | 'send';

/** 按住说话时的全屏录音态：波形 + 取消 / 转文字 / 松开发送 */
export function VoiceRecordingOverlay({
  visible,
  zone,
}: {
  visible: boolean;
  zone: VoiceRecordGestureZone;
}) {
  const bars = useRef(
    Array.from({ length: 16 }, () => new Animated.Value(0.3)),
  ).current;

  useEffect(() => {
    if (!visible) return;
    const anims = bars.map((v, i) =>
      Animated.loop(
        Animated.sequence([
          Animated.timing(v, {
            toValue: 0.25 + ((i * 17) % 7) / 10,
            duration: 220 + (i % 5) * 40,
            useNativeDriver: false,
          }),
          Animated.timing(v, {
            toValue: 0.2 + ((i * 13) % 5) / 12,
            duration: 220 + (i % 4) * 35,
            useNativeDriver: false,
          }),
        ]),
      ),
    );
    anims.forEach((a) => a.start());
    return () => anims.forEach((a) => a.stop());
  }, [visible, bars]);

  const cancelActive = zone === 'cancel';
  const convertActive = zone === 'convert';

  return (
    <InAppModal visible={visible} transparent animationType="fade" statusBarTranslucent>
      <View style={styles.root} pointerEvents="none">
        <View style={styles.centerWrap}>
          <View style={[styles.waveBubble, cancelActive && styles.waveBubbleCancel]}>
            <View style={styles.waveRow}>
              {bars.map((v, i) => (
                <Animated.View
                  key={i}
                  style={[
                    styles.waveBar,
                    {
                      height: v.interpolate({
                        inputRange: [0, 1],
                        outputRange: [6, 36],
                      }),
                      backgroundColor: cancelActive ? '#FFF' : '#0B5F56',
                    },
                  ]}
                />
              ))}
            </View>
          </View>
        </View>

        <View style={styles.bottomPanel}>
          <View style={styles.zoneRow}>
            <View style={[styles.zonePill, cancelActive && styles.zonePillActive]}>
              <Text style={styles.zoneText}>取消</Text>
            </View>
            <View style={[styles.zonePill, convertActive && styles.zonePillActive]}>
              <Text style={styles.zoneText}>滑到这里 转文字</Text>
            </View>
          </View>
          <Text style={styles.hintText}>
            {cancelActive ? '松开 取消' : convertActive ? '松开 转文字' : '松开 发送'}
          </Text>
        </View>
      </View>
    </InAppModal>
  );
}

const styles = StyleSheet.create({
  root: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(0,0,0,0.45)',
    justifyContent: 'flex-end',
  },
  centerWrap: {
    ...StyleSheet.absoluteFillObject,
    alignItems: 'center',
    justifyContent: 'center',
    paddingBottom: 80,
  },
  waveBubble: {
    minWidth: 160,
    paddingHorizontal: 22,
    paddingVertical: 18,
    borderRadius: 12,
    backgroundColor: '#95EC69',
    alignItems: 'center',
    justifyContent: 'center',
  },
  waveBubbleCancel: {
    backgroundColor: '#FA5151',
  },
  waveRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 3,
    height: 40,
  },
  waveBar: {
    width: 3,
    borderRadius: 2,
  },
  bottomPanel: {
    paddingBottom: 36,
    paddingTop: 28,
    paddingHorizontal: 28,
    borderTopLeftRadius: 28,
    borderTopRightRadius: 28,
    backgroundColor: 'rgba(60,60,60,0.92)',
  },
  zoneRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 28,
  },
  zonePill: {
    paddingHorizontal: 18,
    paddingVertical: 10,
    borderRadius: 20,
    backgroundColor: 'rgba(255,255,255,0.12)',
  },
  zonePillActive: {
    backgroundColor: 'rgba(255,255,255,0.28)',
  },
  zoneText: {
    color: '#FFF',
    fontSize: 14,
    fontWeight: '500',
  },
  hintText: {
    textAlign: 'center',
    color: 'rgba(255,255,255,0.85)',
    fontSize: 15,
    fontWeight: '500',
  },
});
