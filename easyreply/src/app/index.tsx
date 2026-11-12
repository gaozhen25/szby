// ============================================================
// 轻回 App - 启动入口
// 根布局已完成会话 hydrate；此处只做路由分流
// ============================================================
import { useEffect } from 'react';
import { View, Text, StyleSheet, ActivityIndicator } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { router } from 'expo-router';
import { isLoggedIn } from '@/core/auth';
import { waitForAuthBootstrap } from '@/core/auth-flow';
import { ScreenCanvas } from '@/components/UI/ScreenCanvas';
import { useTheme } from '@/design/theme-context';
import { APP_NAME } from '@/lib/api-host';

export default function HomeScreen() {
  const theme = useTheme();

  useEffect(() => {
    let alive = true;
    void (async () => {
      await waitForAuthBootstrap();
      if (!alive) return;
      if (isLoggedIn()) {
        router.replace('/(tabs)/chat');
      } else {
        router.replace('/login');
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  return (
    <ScreenCanvas>
      <StatusBar style="auto" />
      <View style={styles.content}>
        <Text style={[styles.title, { color: theme.text }]}>{APP_NAME}</Text>
        <ActivityIndicator color={theme.primary} style={styles.spinner} />
      </View>
    </ScreenCanvas>
  );
}

const styles = StyleSheet.create({
  content: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  title: {
    fontSize: 28,
    fontWeight: '700',
    marginBottom: 8,
  },
  spinner: {
    marginTop: 12,
  },
});
