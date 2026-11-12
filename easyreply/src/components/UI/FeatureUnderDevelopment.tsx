// ============================================================
// 功能未上线占位（正式环境等场景）
// ============================================================
import { StyleSheet, Text, View } from 'react-native';
import { ToolOutlined } from '@/ui/antd-icons';
import { StatusBar } from 'expo-status-bar';

import { ScreenCanvas } from '@/components/UI/ScreenCanvas';
import { ScreenHeader } from '@/components/UI/ScreenHeader';
import { useTheme } from '@/design/theme-context';
import { Tokens } from '@/design/tokens';

type Props = {
  title: string;
  subtitle?: string;
};

/** Tab/功能页在正式环境未开放时的统一占位 */
export function FeatureUnderDevelopment({ title, subtitle }: Props) {
  const theme = useTheme();

  return (
    <ScreenCanvas>
      <StatusBar style="dark" />
      <View style={styles.page}>
        <ScreenHeader embedded title={title} subtitle={subtitle} />
        <View style={styles.body}>
          <ToolOutlined size={48} color={theme.placeholder} />
          <Text style={[styles.text, { color: theme.textSubtle }]}>功能正在开发中</Text>
        </View>
      </View>
    </ScreenCanvas>
  );
}

const styles = StyleSheet.create({
  page: {
    flex: 1,
    paddingHorizontal: Tokens.spacing[4],
    paddingTop: Tokens.spacing[2],
  },
  body: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: Tokens.spacing[3],
    paddingBottom: Tokens.spacing[9],
  },
  text: {
    ...Tokens.typography.body,
    fontWeight: '500',
  },
});
