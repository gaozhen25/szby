import React from 'react';
import { StyleSheet, Text, View, type StyleProp, type TextStyle, type ViewStyle } from 'react-native';

import { useTheme } from '@/design/theme-context';
import { Tokens } from '@/design/tokens';

export type ScreenHeaderProps = {
  title: string;
  subtitle?: string;
  /** 紧跟标题右侧的附属内容（如状态按钮） */
  titleAccessory?: React.ReactNode;
  right?: React.ReactNode;
  /** 嵌入固定表头区域时使用，省略外层上下间距 */
  embedded?: boolean;
  style?: StyleProp<ViewStyle>;
  titleStyle?: StyleProp<TextStyle>;
  subtitleStyle?: StyleProp<TextStyle>;
};

/** Tab 一级页面统一表头：标题 + 副标题 + 可选右侧操作区 */
export function ScreenHeader({
  title,
  subtitle,
  titleAccessory,
  right,
  embedded,
  style,
  titleStyle,
  subtitleStyle,
}: ScreenHeaderProps) {
  const theme = useTheme();

  return (
    <View style={[styles.root, !embedded && styles.standalone, style]}>
      <View style={styles.body}>
        <View style={styles.titleRow}>
          <Text style={[styles.title, { color: theme.text }, titleStyle]}>{title}</Text>
          {titleAccessory ? <View style={styles.titleAccessory}>{titleAccessory}</View> : null}
        </View>
        {subtitle ? (
          <Text style={[styles.subtitle, { color: theme.textSubtle }, subtitleStyle]}>{subtitle}</Text>
        ) : null}
      </View>
      {right ? <View style={styles.right}>{right}</View> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
  },
  standalone: {
    paddingTop: Tokens.spacing[2],
    paddingBottom: Tokens.spacing[4],
  },
  body: {
    flex: 1,
    minWidth: 0,
    gap: Tokens.spacing[1],
    paddingRight: Tokens.spacing[3],
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: Tokens.spacing[2],
  },
  title: {
    ...Tokens.typography.navPrimary,
  },
  titleAccessory: {
    flexShrink: 0,
  },
  subtitle: {
    ...Tokens.typography.caption,
  },
  right: {
    flexShrink: 0,
    alignSelf: 'flex-start',
  },
});

export default ScreenHeader;
