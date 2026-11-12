import { useCallback, useEffect, useState } from 'react';
import { Avatar, Button, Empty, Flex, Spin, Typography } from 'antd';
import { MessageOutlined, ReloadOutlined } from '@/ui/web/antd-icons';
import { fetchClaimedTasks } from '@/api/tasks';
import {
  sortTasksByLastTriggerMsgTime,
  taskToSessionRow,
  type TaskSessionRow,
} from '@/lib/task-session-list';
import { chromeCssVars } from '@/ui/web/chrome-theme';
import { webColor, webFontSize, webLayout, webType } from '@/ui/web/theme';
import { WebOverlayScroll } from '@/ui/web/chat/WebOverlayScroll';

export function AnnotatorSessionsPane({
  agentId,
  name,
  maxActiveCap,
  selectedTaskId,
  onSelectSession,
}: {
  agentId: string;
  name?: string;
  maxActiveCap?: number | null;
  selectedTaskId?: string;
  onSelectSession: (taskId: string) => void;
}) {
  const annotatorId = agentId.trim();
  const [sessions, setSessions] = useState<TaskSessionRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const loadSessions = useCallback(async () => {
    if (!annotatorId) return [];
    const res = await fetchClaimedTasks({ annotatorID: annotatorId });
    const sorted = sortTasksByLastTriggerMsgTime(res?.tasks ?? []);
    return sorted.map(taskToSessionRow);
  }, [annotatorId]);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    void loadSessions()
      .then((items) => {
        if (alive) setSessions(items);
      })
      .catch(() => {
        if (alive) setSessions([]);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [loadSessions]);

  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      setSessions(await loadSessions());
    } catch {
      setSessions([]);
    } finally {
      setRefreshing(false);
    }
  }, [loadSessions]);

  const sessionCountLabel = loading
    ? '加载会话…'
    : maxActiveCap != null
      ? `进行中 ${sessions.length}/${maxActiveCap} 个`
      : `进行中 ${sessions.length} 个`;

  return (
    <Flex vertical flex={1} style={{ minHeight: 0, background: chromeCssVars.convPaneBg }}>
      <Flex align="center" justify="space-between" style={{ padding: '8px 16px 4px', flexShrink: 0 }}>
        <Typography.Text style={webType.pageSubtitle}>
          {sessionCountLabel}
        </Typography.Text>
        <Button
          type="text"
          size="small"
          icon={<ReloadOutlined />}
          loading={refreshing}
          onClick={() => void handleRefresh()}
          title="刷新会话"
          aria-label="刷新会话"
        />
      </Flex>
      {loading ? (
        <Flex flex={1} align="center" justify="center">
          <Spin />
        </Flex>
      ) : sessions.length === 0 ? (
        <Flex flex={1} align="center" justify="center">
          <Empty
            image={<MessageOutlined style={{ fontSize: webFontSize.emptyIcon, color: webColor.primary }} />}
            description={name?.trim() ? `${name.trim()}暂无进行中的会话` : '暂无进行中的会话'}
          />
        </Flex>
      ) : (
        <WebOverlayScroll>
          {sessions.map((item) => {
            const letter = (item.audiencePlatformNickname || item.to || '?').trim().charAt(0) || '?';
            const selected = selectedTaskId === item.id;
            const className = ['qh-conv-row', selected ? 'is-active' : ''].filter(Boolean).join(' ');
            return (
              <Button
                key={item.id}
                type="text"
                block
                className={className}
                aria-current={selected ? 'true' : undefined}
                onClick={() => onSelectSession(item.id)}
              >
                <span className="qh-conv-avatar">
                  <Avatar
                    size={webLayout.convAvatarSize}
                    src={item.audiencePlatformFaceURL?.trim() || undefined}
                    style={{ background: item.avatarColor, color: webColor.onPrimary, border: 'none' }}
                  >
                    {letter}
                  </Avatar>
                </span>
                <Typography.Text ellipsis className="qh-conv-name" style={{ ...webType.nameLabel, flex: 1 }}>
                  {item.from} → {item.to}
                </Typography.Text>
                {item.time ? (
                  <Typography.Text className="qh-conv-time" style={webType.timestamp}>{item.time}</Typography.Text>
                ) : null}
              </Button>
            );
          })}
        </WebOverlayScroll>
      )}
    </Flex>
  );
}
