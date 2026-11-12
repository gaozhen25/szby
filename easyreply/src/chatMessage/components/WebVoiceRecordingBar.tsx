import { useEffect, useRef } from 'react';
import { ActivityIndicator, Animated, Pressable, StyleSheet, View } from 'react-native';
import { ArrowUpOutlined, CloseOutlined } from '@/ui/antd-icons';

/** Web 录音态输入栏：取消 + 波形 + 发送（对齐设计稿） */
export function WebVoiceRecordingBar({
  sending,
  onCancel,
  onSend,
}: {
  sending?: boolean;
  onCancel: () => void;
  onSend: () => void;
}) {
  const bars = useRef(Array.from({ length: 8 }, () => new Animated.Value(0.35))).current;

  useEffect(() => {
    if (sending) return;
    const anims = bars.map((v, i) =>
      Animated.loop(
        Animated.sequence([
          Animated.timing(v, {
            toValue: 0.35 + ((i * 19) % 6) / 10,
            duration: 180 + (i % 4) * 45,
            useNativeDriver: false,
          }),
          Animated.timing(v, {
            toValue: 0.25 + ((i * 11) % 5) / 12,
            duration: 180 + (i % 3) * 40,
            useNativeDriver: false,
          }),
        ]),
      ),
    );
    anims.forEach((a) => a.start());
    return () => anims.forEach((a) => a.stop());
  }, [bars, sending]);

  return (
    <View style={styles.row}>
      <Pressable
        onPress={onCancel}
        disabled={sending}
        hitSlop={8}
        style={({ pressed }) => [styles.cancelBtn, pressed && { opacity: 0.75 }]}
        accessibilityLabel="取消录音"
      >
        <CloseOutlined size={22} color="#C8C8C8" />
      </Pressable>

      <View style={styles.wavePill}>
        <View style={styles.waveRow}>
          {sending ? (
            <ActivityIndicator size="small" color="#34C759" />
          ) : (
            bars.map((v, i) => (
              <Animated.View
                key={i}
                style={[
                  styles.waveBar,
                  {
                    height: v.interpolate({
                      inputRange: [0, 1],
                      outputRange: [4, 22],
                    }),
                  },
                ]}
              />
            ))
          )}
        </View>

        <Pressable
          onPress={onSend}
          disabled={sending}
          hitSlop={6}
          style={({ pressed }) => [styles.sendBtn, pressed && { opacity: 0.85 }]}
          accessibilityLabel="发送语音"
        >
          <ArrowUpOutlined size={20} color="#111" />
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    minHeight: 44,
  },
  cancelBtn: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: '#3A3A3C',
    alignItems: 'center',
    justifyContent: 'center',
  },
  wavePill: {
    flex: 1,
    height: 44,
    borderRadius: 22,
    backgroundColor: '#2C2C2E',
    flexDirection: 'row',
    alignItems: 'center',
    paddingLeft: 18,
    paddingRight: 4,
  },
  waveRow: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 4,
    height: 28,
  },
  waveBar: {
    width: 3.5,
    borderRadius: 2,
    backgroundColor: '#34C759',
  },
  sendBtn: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: '#34C759',
    alignItems: 'center',
    justifyContent: 'center',
  },
});
