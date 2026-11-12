/**
 * THESIS: 主管先认人、再进会话；拒绝表格操作列堆按钮。
 * OWN-WORLD: 与聊天页同一套分栏、选中底、搜索胶囊、字号色值。
 * STORY: 左侧扫状态与任务数，点人选中；右侧看该人会话并可旁观进房。
 * FIRST VIEWPORT: 左栏名册+筛选，右栏空态或该人会话列表。
 * FORM: 聊天分栏在标注员管理上的编排。
 */
import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Avatar, Button, Dropdown, Empty, Flex, Input, Modal, Space, Spin, Typography } from 'antd';
import {
  CheckCircleOutlined,
  EditOutlined,
  LogoutOutlined,
  ReloadOutlined,
  SearchOutlined,
  StopOutlined,
  TeamOutlined,
} from '@/ui/web/antd-icons';
import { router, useLocalSearchParams } from 'expo-router';
import {
  fetchSupervisorAgentsOverview,
  formatSupervisorApiError,
  supervisorForceAgentDutyOff,
  supervisorSetAgentValid,
} from '@/api/supervisor';
import { patchAdminAgent } from '@/api/agents';
import { waitForAuthBootstrap } from '@/core/auth-flow';
import { appAlert } from '@/lib/app-alert';
import { mapOverviewAgentsToAnnotators } from '@/lib/supervisor-agents';
import { type AnnotatorStatus, type MockAnnotator } from '@/mock/data';
import { AnnotatorSessionsPane } from '@/ui/web/pages/AnnotatorSessionsPage';
import { ChatRoomPane } from '@/ui/web/pages/ChatRoomPage';
import { WebOverlayScroll } from '@/ui/web/chat/WebOverlayScroll';
import { WebPaneResizeHandle } from '@/ui/web/WebPaneResizeHandle';
import { chromeCssVars } from '@/ui/web/chrome-theme';
import { webColor, webFontSize, webLayout, webType } from '@/ui/web/theme';

const REFRESH_BTN_COOLDOWN_MS = 5000;

type StatusFilter = 'all' | AnnotatorStatus;

const STATUS_FILTERS: { id: StatusFilter; label: string }[] = [
  { id: 'all', label: '全部' },
  { id: 'online', label: '在线' },
  { id: 'offline', label: '离线' },
  { id: 'disabled', label: '已停用' },
];

function paramStr(value?: string | string[]): string | undefined {
  if (Array.isArray(value)) return value[0];
  return value || undefined;
}

function statusMeta(status: AnnotatorStatus): { label: string; color: string; bg: string } {
  if (status === 'online') {
    return { label: '在线', color: webColor.success, bg: webColor.fileExcelBg };
  }
  if (status === 'disabled') {
    return { label: '已停用', color: webColor.danger, bg: webColor.filePdfBg };
  }
  return { label: '离线', color: webColor.subLabel, bg: webColor.search };
}

function StatusBadge({ status }: { status: AnnotatorStatus }) {
  const meta = statusMeta(status);
  return (
    <span className="qh-annotator-status" style={{ color: meta.color, background: meta.bg }}>
      <span className="qh-annotator-status-dot" style={{ background: meta.color }} />
      {meta.label}
    </span>
  );
}

const AnnotatorRow = memo(function AnnotatorRow({
  item,
  selected,
  onSelect,
  onEditRemark,
  onForceOffline,
  onDisable,
  onEnable,
}: {
  item: MockAnnotator;
  selected: boolean;
  onSelect: (item: MockAnnotator) => void;
  onEditRemark: (item: MockAnnotator) => void;
  onForceOffline: (item: MockAnnotator) => void;
  onDisable: (item: MockAnnotator) => void;
  onEnable: (item: MockAnnotator) => void;
}) {
  const muted = item.status === 'disabled';
  const isOnline = item.status === 'online';
  const className = ['qh-conv-row', muted ? 'is-muted' : '', selected ? 'is-active' : '']
    .filter(Boolean)
    .join(' ');
  const initial = item.name.trim().charAt(0) || 'A';

  const rowButton = (
    <Button
      type="text"
      block
      className={className}
      aria-current={selected ? 'true' : undefined}
      onClick={() => onSelect(item)}
    >
      <span className="qh-conv-avatar">
        <Avatar
          size={webLayout.convAvatarSize}
          style={{ background: webColor.primary, color: webColor.onPrimary, border: 'none' }}
        >
          {initial}
        </Avatar>
      </span>
      <Flex vertical flex={1} style={{ minWidth: 0 }} gap={webLayout.convNamePreviewGap}>
        <Flex align="center" gap={8}>
          <Typography.Text ellipsis className="qh-conv-name" style={{ ...webType.nameLabel, flex: 1 }}>
            {item.name || '未命名'}
          </Typography.Text>
          <StatusBadge status={item.status} />
        </Flex>
        <Typography.Text ellipsis className="qh-conv-sub" style={webType.subLabel}>
          {item.remark.trim() || (item.intakePaused ? '已暂停接待新任务' : '暂无备注')}
        </Typography.Text>
      </Flex>
      <Flex vertical align="flex-end" justify="space-between" style={{ alignSelf: 'stretch', flexShrink: 0 }}>
        <Typography.Text className="qh-conv-time" style={webType.timestamp}>{item.onlineDuration}</Typography.Text>
        <Typography.Text style={{ ...webType.subLabel, color: webColor.nameLabel }}>
          {item.replyCount}
        </Typography.Text>
      </Flex>
    </Button>
  );

  return (
    <Dropdown
      trigger={['contextMenu']}
      menu={{
        items: muted
          ? [
              { key: 'remark', icon: <EditOutlined />, label: '修改备注' },
              { key: 'enable', icon: <CheckCircleOutlined />, label: '启用账号' },
            ]
          : [
              { key: 'remark', icon: <EditOutlined />, label: '修改备注' },
              ...(isOnline
                ? [{ key: 'force-off', icon: <LogoutOutlined />, label: '强制下班' }]
                : []),
              { key: 'disable', icon: <StopOutlined />, danger: true, label: '停用账号' },
            ],
        onClick: ({ key }) => {
          if (key === 'remark') onEditRemark(item);
          if (key === 'force-off') onForceOffline(item);
          if (key === 'disable') onDisable(item);
          if (key === 'enable') onEnable(item);
        },
      }}
    >
      {rowButton}
    </Dropdown>
  );
});

export default function AnnotatorsPage() {
  const params = useLocalSearchParams<{ agentId?: string; name?: string; taskId?: string }>();
  const selectedId = paramStr(params.agentId);
  const previewTaskId = paramStr(params.taskId);
  const [annotators, setAnnotators] = useState<MockAnnotator[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState<StatusFilter>('all');
  const [keyword, setKeyword] = useState('');
  const [editing, setEditing] = useState<MockAnnotator | null>(null);
  const [remarkDraft, setRemarkDraft] = useState('');
  const [savingRemark, setSavingRemark] = useState(false);
  const [refreshBtnCooldown, setRefreshBtnCooldown] = useState(false);
  const [sessionsEpoch, setSessionsEpoch] = useState(0);
  const remarksRef = useRef<Record<string, string>>({});
  const refreshBtnCooldownTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadAnnotators = useCallback(async () => {
    const res = await fetchSupervisorAgentsOverview();
    if (!res.ok) return;
    const agents = res.agents ?? [];
    for (const a of agents) {
      const fromApi = a.additional_info?.trim();
      if (fromApi && !remarksRef.current[a.agent_id]?.trim()) {
        remarksRef.current[a.agent_id] = fromApi;
      }
    }
    setAnnotators(mapOverviewAgentsToAnnotators(agents, remarksRef.current));
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        await waitForAuthBootstrap();
        if (cancelled) return;
        await loadAnnotators();
      } catch (e) {
        console.warn('[annotators] overview failed', e);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [loadAnnotators]);

  useEffect(() => {
    return () => {
      if (refreshBtnCooldownTimerRef.current) clearTimeout(refreshBtnCooldownTimerRef.current);
    };
  }, []);

  const handleRefresh = useCallback(async () => {
    if (refreshing) return;
    setRefreshing(true);
    try {
      await loadAnnotators();
    } catch (e) {
      console.warn('[annotators] refresh failed', e);
    } finally {
      setRefreshing(false);
    }
  }, [loadAnnotators, refreshing]);

  const handleManualRefresh = useCallback(async () => {
    if (refreshing || refreshBtnCooldown) return;
    try {
      await handleRefresh();
    } finally {
      setRefreshBtnCooldown(true);
      if (refreshBtnCooldownTimerRef.current) clearTimeout(refreshBtnCooldownTimerRef.current);
      refreshBtnCooldownTimerRef.current = setTimeout(() => {
        setRefreshBtnCooldown(false);
        refreshBtnCooldownTimerRef.current = null;
      }, REFRESH_BTN_COOLDOWN_MS);
    }
  }, [handleRefresh, refreshing, refreshBtnCooldown]);

  const counts = useMemo(() => {
    const result: Record<StatusFilter, number> = {
      all: annotators.length,
      online: 0,
      offline: 0,
      disabled: 0,
    };
    for (const a of annotators) result[a.status] += 1;
    return result;
  }, [annotators]);

  const filtered = useMemo(() => {
    const q = keyword.trim().toLowerCase();
    return annotators.filter((a) => {
      if (filter !== 'all' && a.status !== filter) return false;
      if (!q) return true;
      return a.name.toLowerCase().includes(q) || a.remark.toLowerCase().includes(q);
    });
  }, [annotators, filter, keyword]);

  const selected = useMemo(
    () => annotators.find((a) => (a.agentId ?? a.id) === selectedId),
    [annotators, selectedId],
  );

  const selectAnnotator = useCallback((item: MockAnnotator) => {
    const agentId = item.agentId ?? item.id;
    if (agentId === selectedId) return;
    router.setParams({ agentId, name: item.name, taskId: '' });
  }, [selectedId]);

  const selectPreviewSession = useCallback(
    (taskId: string) => {
      const id = taskId.trim();
      if (!id || !selectedId) return;
      if (id === previewTaskId) return;
      router.setParams({ agentId: selectedId, name: paramStr(params.name), taskId: id });
    },
    [previewTaskId, selectedId, params.name],
  );

  const handleSupervisorTakeoverComplete = useCallback((taskId: string) => {
    const id = taskId.trim();
    if (!id) return;
    router.replace({
      pathname: '/(tabs)/chat',
      params: { id },
    });
  }, []);

  const openEditRemark = useCallback((annotator: MockAnnotator) => {
    setEditing(annotator);
    setRemarkDraft(annotator.remark ?? '');
  }, []);

  const handleSaveRemark = useCallback(async () => {
    if (!editing) return;
    const id = editing.agentId ?? editing.id;
    const remark = remarkDraft.trim();
    setSavingRemark(true);
    try {
      const res = await patchAdminAgent(id, { additional_info: remark });
      if (!res.ok) throw new Error('保存失败');
      remarksRef.current[id] = remark;
      setAnnotators((prev) => prev.map((x) => (x.id === editing.id ? { ...x, remark } : x)));
      setEditing(null);
    } catch (e) {
      appAlert('保存失败', e instanceof Error ? e.message : '请稍后重试');
    } finally {
      setSavingRemark(false);
    }
  }, [editing, remarkDraft]);

  const handleForceOffline = useCallback(
    (annotator: MockAnnotator) => {
      appAlert(
        '强制下班',
        `确定将「${annotator.name}」强制下班？其当前持有的会话将被回收并重新分配，账号不会停用，对方可自行重新上班。`,
        [
          { text: '取消', style: 'cancel' },
          {
            text: '确认下班',
            style: 'destructive',
            onPress: () => {
              void supervisorForceAgentDutyOff(annotator.agentId ?? annotator.id)
                .then(async (res) => {
                  if (!res.ok) {
                    appAlert('强制下班失败', '请稍后重试');
                    return;
                  }
                  const reclaimed = typeof res.reclaimedTaskCount === 'number' ? res.reclaimedTaskCount : 0;
                  appAlert('已强制下班', `已强制「${annotator.name}」下班，回收任务 ${reclaimed} 个`);
                  await handleRefresh();
                  setSessionsEpoch((n) => n + 1);
                })
                .catch((e) => appAlert('强制下班失败', formatSupervisorApiError(e)));
            },
          },
        ],
      );
    },
    [handleRefresh],
  );

  const handleDisable = useCallback(
    (annotator: MockAnnotator) => {
      appAlert('停用标注员账号', `确定停用「${annotator.name}」的账号？停用后该标注员将无法登录系统，此操作需谨慎。`, [
        { text: '取消', style: 'cancel' },
        {
          text: '确认停用',
          style: 'destructive',
          onPress: () => {
            void supervisorSetAgentValid(annotator.agentId ?? annotator.id, false)
              .then(async (res) => {
                if (!res.ok) {
                  appAlert('停用失败', '请稍后重试');
                  return;
                }
                const reclaimed = typeof res.reclaimedTaskCount === 'number' ? res.reclaimedTaskCount : 0;
                const forced = res.forced_offline ? '，已强制下线' : '';
                appAlert('已停用账号', `已停用「${annotator.name}」账号，回收任务 ${reclaimed} 个${forced}`);
                await handleRefresh();
              })
              .catch((e) => appAlert('停用失败', e instanceof Error ? e.message : '请稍后重试'));
          },
        },
      ]);
    },
    [handleRefresh],
  );

  const handleEnable = useCallback(
    (annotator: MockAnnotator) => {
      appAlert('启用标注员账号', `确定启用「${annotator.name}」的账号？启用后该标注员仍需自行上班才会参与自动领取。`, [
        { text: '取消', style: 'cancel' },
        {
          text: '确认启用',
          onPress: () => {
            void supervisorSetAgentValid(annotator.agentId ?? annotator.id, true)
              .then(async (res) => {
                if (!res.ok) {
                  appAlert('启用失败', '请稍后重试');
                  return;
                }
                appAlert('已启用账号', `已启用「${annotator.name}」账号`);
                await handleRefresh();
              })
              .catch((e) => appAlert('启用失败', e instanceof Error ? e.message : '请稍后重试'));
          },
        },
      ]);
    },
    [handleRefresh],
  );

  const isDisabled = selected?.status === 'disabled';
  const isOnline = selected?.status === 'online';
  const splitClassName = previewTaskId
    ? 'qh-annotator-split qh-annotator-split--with-chat'
    : 'qh-annotator-split';

  return (
    <Flex className={splitClassName}>
      <Flex vertical className="qh-annotator-list-pane">
        <Flex align="center" gap={8} style={{ padding: '10px 16px', flexShrink: 0 }}>
          <Flex vertical style={{ flex: 1, minWidth: 0 }} gap={0}>
            <Typography.Title level={4} style={webType.paneTitle}>
              标注员
            </Typography.Title>
            <Typography.Text type="secondary" style={webType.pageSubtitle}>
              共 {annotators.length} 人
            </Typography.Text>
          </Flex>
          <Button
            type="text"
            size="small"
            icon={<ReloadOutlined />}
            loading={refreshing}
            disabled={refreshBtnCooldown || loading}
            onClick={() => void handleManualRefresh()}
            title="刷新标注员列表"
            aria-label="刷新标注员列表"
          />
        </Flex>

        <Flex className="qh-conv-toolbar">
          <Input
            className="qh-conv-search"
            allowClear
            variant="borderless"
            prefix={<SearchOutlined />}
            placeholder="搜索账号或备注"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
          />
        </Flex>

        <div className="qh-annotator-filters">
          {STATUS_FILTERS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`qh-annotator-chip${filter === item.id ? ' is-active' : ''}`}
              onClick={() => setFilter(item.id)}
            >
              {item.label}
              <span className="qh-annotator-chip-count">{counts[item.id]}</span>
            </button>
          ))}
        </div>

        {loading ? (
          <Flex flex={1} align="center" justify="center">
            <Spin />
          </Flex>
        ) : filtered.length === 0 ? (
          <Flex flex={1} align="center" justify="center">
            <Empty description={annotators.length === 0 ? '暂无标注员' : '没有符合条件的标注员'} />
          </Flex>
        ) : (
          <WebOverlayScroll>
            {filtered.map((item) => (
              <AnnotatorRow
                key={item.id}
                item={item}
                selected={(item.agentId ?? item.id) === selectedId}
                onSelect={selectAnnotator}
                onEditRemark={openEditRemark}
                onForceOffline={handleForceOffline}
                onDisable={handleDisable}
                onEnable={handleEnable}
              />
            ))}
          </WebOverlayScroll>
        )}
        <WebPaneResizeHandle pane="actor" />
      </Flex>

      <Flex vertical className="qh-annotator-detail-pane">
        {selectedId ? (
          <>
            <div className="qh-annotator-detail-header">
              <Flex align="center" gap={12}>
                <Avatar size={40} style={{ background: webColor.primary, color: webColor.onPrimary, flexShrink: 0 }}>
                  {(selected?.name || paramStr(params.name) || '?').trim().charAt(0) || '?'}
                </Avatar>
                <Flex vertical flex={1} style={{ minWidth: 0 }} gap={4}>
                  <Flex align="center" gap={8} style={{ minWidth: 0 }}>
                    <Typography.Title
                      level={4}
                      ellipsis
                      style={{ ...webType.paneTitle, flex: '0 1 auto', minWidth: 0, maxWidth: '100%' }}
                    >
                      {selected?.name || paramStr(params.name) || '标注员'}
                    </Typography.Title>
                    {selected ? <StatusBadge status={selected.status} /> : null}
                  </Flex>
                  <Typography.Text ellipsis style={webType.subLabel}>
                    {selected?.remark.trim() || '暂无备注'}
                  </Typography.Text>
                </Flex>
              </Flex>
              <Space size={8} wrap>
                {selected && isDisabled ? (
                  <Button
                    size="small"
                    icon={<CheckCircleOutlined />}
                    onClick={() => handleEnable(selected)}
                  >
                    启用账号
                  </Button>
                ) : selected ? (
                  <>
                    <Button
                      size="small"
                      icon={<EditOutlined />}
                      onClick={() => openEditRemark(selected)}
                    >
                      修改备注
                    </Button>
                    {isOnline ? (
                      <Button
                        size="small"
                        icon={<LogoutOutlined />}
                        onClick={() => handleForceOffline(selected)}
                      >
                        强制下班
                      </Button>
                    ) : null}
                    <Button
                      size="small"
                      danger
                      icon={<StopOutlined />}
                      onClick={() => handleDisable(selected)}
                    >
                      停用账号
                    </Button>
                  </>
                ) : null}
              </Space>
            </div>
            <AnnotatorSessionsPane
              key={`${selectedId}:${sessionsEpoch}`}
              agentId={selectedId}
              name={selected?.name || paramStr(params.name)}
              maxActiveCap={selected?.maxActiveCap}
              selectedTaskId={previewTaskId}
              onSelectSession={selectPreviewSession}
            />
          </>
        ) : (
          <Flex flex={1} align="center" justify="center" style={{ height: '100%', background: chromeCssVars.convPaneBg }}>
            <Empty
              image={<TeamOutlined style={{ fontSize: webFontSize.emptyIcon, color: webColor.primary }} />}
              description="从左侧选择一位标注员查看会话"
            />
          </Flex>
        )}
        {previewTaskId ? <WebPaneResizeHandle pane="conv" /> : null}
      </Flex>

      {previewTaskId && selectedId ? (
        <Flex vertical className="qh-annotator-chat-pane">
          <ChatRoomPane
            key={`${previewTaskId}:${selectedId}`}
            taskID={previewTaskId}
            annotatorId={selectedId}
            supervisorParam
            onSupervisorTakeoverComplete={handleSupervisorTakeoverComplete}
          />
        </Flex>
      ) : null}

      <Modal
        open={!!editing}
        title="修改备注"
        okText={savingRemark ? '保存中…' : '保存'}
        confirmLoading={savingRemark}
        onCancel={() => setEditing(null)}
        onOk={() => void handleSaveRemark()}
      >
        <Typography.Paragraph style={webType.modalSubtitle}>
          {editing?.name}
        </Typography.Paragraph>
        <Input.TextArea
          rows={4}
          maxLength={200}
          value={remarkDraft}
          placeholder="输入备注信息，如班次、擅长类目等"
          onChange={(e) => setRemarkDraft(e.target.value)}
        />
      </Modal>
    </Flex>
  );
}
