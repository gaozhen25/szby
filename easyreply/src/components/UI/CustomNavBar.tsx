// ============================================================
// 自定义导航栏（返回 + 居中标题）
// ============================================================
import type { ReactNode } from 'react';
import { Pressable, StyleSheet, Text, View, type StyleProp, type TextStyle, type ViewStyle } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useTheme } from '@/design/theme-context';
import { ArrowLeftOutlined } from '@/ui/antd-icons';
import { Tokens } from '@/design/tokens';

const PROACTIVE_HINT_DOT = '#FACC15';

type Props = {
  title: string;
  onBack: () => void;
  right?: ReactNode;
  style?: ViewStyle;
  titleStyle?: StyleProp<TextStyle>;
  /** 右侧区域最小宽度，默认 40；多按钮场景可传更大值 */
  rightMinWidth?: number;
  /** 返回按钮旁红点（其它会话有未读红点时提示） */
  showBackRedDot?: boolean;
  /** 返回按钮旁黄点（其它会话有主动触达提醒时提示） */
  showBackYellowDot?: boolean;
};

export function CustomNavBar({
  title,
  onBack,
  right,
  style,
  titleStyle,
  rightMinWidth = 40,
  showBackRedDot = false,
  showBackYellowDot = false,
}: Props) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const showDots = showBackYellowDot || showBackRedDot;

  return (
    <View
      style={[
        styles.bar,
        {
          borderBottomColor: theme.divider,
          backgroundColor: theme.surface,
          paddingTop: insets.top,
        },
        style,
      ]}
    >
      <View style={styles.contentRow}>
        <Pressable onPress={onBack} hitSlop={12} style={styles.side}>
          <View style={styles.backIconWrap}>
            <ArrowLeftOutlined size={24} color={theme.text} />
            {showDots ? (
              <View style={styles.backDotRow}>
                {showBackYellowDot ? (
                  <View
                    style={[
                      styles.backDot,
                      { backgroundColor: PROACTIVE_HINT_DOT, borderColor: theme.surface },
                    ]}
                  />
                ) : null}
                {showBackRedDot ? (
                  <View
                    style={[
                      styles.backDot,
                      showBackYellowDot && styles.backDotOverlap,
                      { backgroundColor: theme.danger, borderColor: theme.surface },
                    ]}
                  />
                ) : null}
              </View>
            ) : null}
          </View>
        </Pressable>
        <View style={[styles.sideRight, { minWidth: rightMinWidth }]}>{right ?? null}</View>
        <View style={styles.titleLayer} pointerEvents="none">
          <Text
            style={[styles.title, { color: theme.text }, titleStyle]}
            numberOfLines={1}
            ellipsizeMode="middle"
          >
            {title}
          </Text>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  bar: {
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  contentRow: {
    position: 'relative',
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: Tokens.spacing[2],
    paddingTop: Tokens.spacing[2],
    paddingBottom: Tokens.spacing[3],
    minHeight: 40,
  },
  side: {
    width: 40,
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 1,
  },
  backIconWrap: {
    width: 28,
    height: 28,
    alignItems: 'center',
    justifyContent: 'center',
  },
  backDotRow: {
    position: 'absolute',
    right: -17,
    flexDirection: 'row',
    alignItems: 'center',
  },
  backDot: {
    width: 16,
    height: 16,
    borderRadius: 8,
    borderWidth: 2,
  },
  backDotOverlap: {
    marginLeft: -Math.round(16 / 3),
    zIndex: 1,
  },
  sideRight: {
    marginLeft: 'auto',
    paddingRight: Tokens.spacing[3],
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'flex-end',
    gap: Tokens.spacing[4],
    minHeight: 40,
    zIndex: 1,
  },
  titleLayer: {
    ...StyleSheet.absoluteFillObject,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: Tokens.spacing[2],
  },
  title: {
    width: '100%',
    textAlign: 'center',
    ...Tokens.typography.navSecondary,
  },
});

export default CustomNavBar;
