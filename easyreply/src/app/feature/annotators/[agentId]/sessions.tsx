// ============================================================
// 主管查看某标注员（客服）的当前任务会话列表
// - 仅 REST 拉取 claimed/list，不订阅各会话实时消息
// - 点击进入聊天页后加载历史；聊天页内调用 enter_thread / exit_thread 订阅与取消旁观推送
// ============================================================
import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { router, useLocalSearchParams } from 'expo-router';

import { CustomNavBar } from '@/components/UI/CustomNavBar';
import { ScreenCanvas } from '@/components/UI/ScreenCanvas';
import { SupervisorSessionRow } from '@/chatMessage';
import { useTheme } from '@/design/theme-context';
import { Tokens } from '@/design/tokens';
import { fetchClaimedTasks } from '@/api/tasks';
import {
  sortTasksByLastTriggerMsgTime,
  taskToSessionRow,
  type TaskSessionRow,
} from '@/lib/task-session-list';

export default function AnnotatorSessionsScreen() {
  const theme = useTheme();
  const { agentId, name } = useLocalSearchParams<{ agentId: string; name?: string }>();
  const annotatorId = agentId ?? '';
  const title = name?.trim() || '标注员会话';

  const [sessions, setSessions] = useState<TaskSessionRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const loadSessions = useCallback(async () => {
    const res = await fetchClaimedTasks({ annotatorID: annotatorId });
    const sorted = sortTasksByLastTriggerMsgTime(res?.tasks ?? []);
    return sorted.map(taskToSessionRow);
  }, [annotatorId]);

  useEffect(() => {
    let alive = true;
    (async () => {
      setLoading(true);
      try {
        const items = await loadSessions();
        if (alive) setSessions(items);
      } catch {
        if (alive) setSessions([]);
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [loadSessions]);

  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      const items = await loadSessions();
      setSessions(items);
    } catch {
      setSessions([]);
    } finally {
      setRefreshing(false);
    }
  }, [loadSessions]);

  const handleOpenChat = useCallback((taskId: string) => {
    router.push({
      pathname: '/chat/[id]',
      params: {
        id: taskId,
        supervisor: '1',
        annotatorId,
      },
    });
  }, [annotatorId]);

  const handleAssignActors = useCallback(() => {
    router.push({
      pathname: '/feature/annotators/[agentId]/assign-actors',
      params: {
        agentId: annotatorId,
        name: title,
      },
    });
  }, [annotatorId, title]);

  return (
    <ScreenCanvas safeAreaTop={false}>
      <StatusBar style="dark" />
      <CustomNavBar
        title={title}
        onBack={() => router.back()}
        // rightMinWidth={88}
        // right={
        //   <Pressable
        //     onPress={handleAssignActors}
        //     hitSlop={8}
        //     style={({ pressed }) => [styles.assignBtn, pressed && { opacity: 0.7 }]}
        //   >
        //     <UserAddOutlined size={18} color={theme.primary} />
        //     <Text style={[styles.assignText, { color: theme.primary }]}>指派客户</Text>
        //   </Pressable>
        // }
      />
      <View style={styles.page}>
        {loading ? (
          <View style={styles.loadingWrap}>
            <ActivityIndicator color={theme.primary} />
          </View>
        ) : (
          <FlatList
            data={sessions}
            keyExtractor={(item) => item.id}
            renderItem={({ item }) => (
              <SupervisorSessionRow item={item} onPress={handleOpenChat} />
            )}
            contentContainerStyle={[
              styles.listContent,
              sessions.length === 0 && styles.listContentEmpty,
            ]}
            showsVerticalScrollIndicator={false}
            ListEmptyComponent={(
              <View style={styles.empty}>
                <Text style={[styles.emptyText, { color: theme.textSubtle }]}>暂无会话</Text>
              </View>
            )}
            refreshControl={(
              <RefreshControl
                refreshing={refreshing}
                onRefresh={handleRefresh}
                tintColor={theme.primary}
                colors={[theme.primary]}
              />
            )}
          />
        )}
      </View>
    </ScreenCanvas>
  );
}

const styles = StyleSheet.create({
  page: {
    flex: 1,
    paddingHorizontal: Tokens.spacing[4],
  },
  assignBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  assignText: {
    fontSize: 14,
    fontWeight: '600',
  },
  loadingWrap: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  listContent: {
    paddingBottom: Tokens.spacing[4],
  },
  listContentEmpty: {
    flexGrow: 1,
  },
  empty: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingTop: Tokens.spacing[8],
  },
  emptyText: {
    fontSize: 14,
  },
});
