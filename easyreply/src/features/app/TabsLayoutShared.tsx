// ============================================================
// 主 TabBar 布局（原生 + Web 窄屏共用；Web 桌面隐藏 TabBar）
// ============================================================
import { useEffect, useState } from 'react';
import { Tabs } from 'expo-router';
import { Platform, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { BounceTabBarButton } from '@/components/UI/BounceTabBarButton';
import { useTheme } from '@/design/theme-context';
import { getRole } from '@/core/auth';
import {
  ensureClaimedConversationsHydrated,
  getClaimedConversationsSnapshot,
  hasVisibleConversationProactiveHint,
  hasVisibleConversationRedDot,
  subscribeClaimedConversations,
} from '@/lib/claimed-conversations-store';
import { resolveBottomInset } from '@/lib/safe-area-bottom';
import {
  BarChartOutlined,
  CalculatorOutlined,
  MessageOutlined,
  TeamOutlined,
} from '@/ui/antd-icons';
import { ProfileTabGlyph } from '@/ui/mobile-glyphs';

const PROACTIVE_HINT_DOT = '#FACC15';
/** Tab 内容区高度（不含系统底部手势/导航条） */
const TAB_BAR_CONTENT_HEIGHT = Platform.OS === 'ios' ? 49 : 56;

function ChatTabIcon({ color, size }: { color: string; size: number }) {
  const theme = useTheme();
  const [chatHasRedDot, setChatHasRedDot] = useState(() =>
    hasVisibleConversationRedDot(getClaimedConversationsSnapshot()),
  );
  const [chatHasYellowDot, setChatHasYellowDot] = useState(() =>
    hasVisibleConversationProactiveHint(getClaimedConversationsSnapshot()),
  );

  useEffect(() => {
    void ensureClaimedConversationsHydrated();
    return subscribeClaimedConversations((list) => {
      setChatHasRedDot(hasVisibleConversationRedDot(list));
      setChatHasYellowDot(hasVisibleConversationProactiveHint(list));
    });
  }, []);

  return (
    <View style={styles.tabIconWrap}>
      <MessageOutlined size={size} color={color} />
      {chatHasYellowDot || chatHasRedDot ? (
        <View style={styles.tabDotRow}>
          {chatHasYellowDot ? (
            <View
              style={[
                styles.tabDot,
                { backgroundColor: PROACTIVE_HINT_DOT, borderColor: theme.surface },
              ]}
            />
          ) : null}
          {chatHasRedDot ? (
            <View
              style={[
                styles.tabDot,
                chatHasYellowDot && styles.tabDotOverlap,
                { backgroundColor: theme.danger, borderColor: theme.surface },
              ]}
            />
          ) : null}
        </View>
      ) : null}
    </View>
  );
}

export function TabsLayoutShared({ hideTabBar = false }: { hideTabBar?: boolean }) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const bottomInset = resolveBottomInset(insets.bottom);
  const isSupervisor = getRole() === 'supervisor';

  const tabBarStyle = hideTabBar
    ? { display: 'none' as const, height: 0 }
    : {
        backgroundColor: theme.surface,
        borderTopColor: theme.border,
        borderTopWidth: 1,
        height: TAB_BAR_CONTENT_HEIGHT + bottomInset + 6,
        paddingTop: 6,
        paddingBottom: bottomInset,
      };

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarButton: (props) => <BounceTabBarButton {...props} />,
        tabBarActiveTintColor: theme.primary,
        tabBarInactiveTintColor: theme.text,
        tabBarLabelStyle: {
          fontSize: 10,
          fontWeight: '500',
          marginBottom: Platform.OS === 'ios' ? 0 : 2,
        },
        tabBarStyle,
        tabBarItemStyle: {
          paddingBottom: 0,
        },
      }}
    >
      <Tabs.Screen
        name="chat"
        options={{
          title: '聊天',
          tabBarIcon: ({ color, size }) => <ChatTabIcon color={color} size={size} />,
        }}
      />
      <Tabs.Screen
        name="annotators"
        options={{
          title: '标注员',
          href: isSupervisor ? undefined : null,
          tabBarIcon: ({ color, size }) => <TeamOutlined size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="performance-settlement"
        options={{
          title: '绩效核算',
          href: isSupervisor ? undefined : null,
          tabBarIcon: ({ color, size }) => <CalculatorOutlined size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="performance"
        options={{
          title: '绩效中心',
          href: isSupervisor ? null : undefined,
          tabBarIcon: ({ color, size }) => <BarChartOutlined size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="profile"
        options={{
          title: '我的',
          tabBarIcon: ({ color, size }) => <ProfileTabGlyph size={size} color={color} />,
        }}
      />
    </Tabs>
  );
}

const styles = StyleSheet.create({
  tabIconWrap: {
    width: 28,
    height: 28,
    alignItems: 'center',
    justifyContent: 'center',
  },
  tabDotRow: {
    position: 'absolute',
    top: -6,
    right: -12,
    flexDirection: 'row',
    alignItems: 'center',
  },
  tabDot: {
    width: 16,
    height: 16,
    borderRadius: 8,
    borderWidth: 2,
  },
  tabDotOverlap: {
    marginLeft: -Math.round(16 / 3),
    zIndex: 1,
  },
});
