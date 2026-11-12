import { useEffect, useState, type CSSProperties, type ReactNode } from 'react';
import { Flex, Layout, Menu, Popover, Typography, Avatar } from 'antd';
import type { MenuProps } from 'antd';
import {
  BarChartOutlined,
  CalculatorOutlined,
  // UpOutlined,
  MessageOutlined,
  SettingOutlined,
  TeamOutlined,
} from '@/ui/web/antd-icons';
import { router, usePathname } from 'expo-router';
import { getAgentAccount, getRole, getUserInfo, subscribeUserInfo } from '@/core/auth';
import { APP_NAME } from '@/lib/api-host';
import {
  getChatListView,
  setChatListView,
  subscribeChatListView,
} from '@/lib/chat-list-view-bus';
import {
  getSiderActorBrand,
  hydrateSiderActorBrand,
  subscribeSiderActorBrand,
  type SiderActorBrand,
} from '@/lib/sider-actor-brand-bus';
import { useDutyControls } from '@/features/conversations/useDutyControls';
import { useIntakeControls } from '@/features/conversations/useIntakeControls';
import { useProfile } from '@/features/profile/useProfile';
import {
  closeProfileModal,
  getProfileModalView,
  openProfileModal,
  subscribeProfileModal,
} from '@/lib/profile-modal-bus';
import { SiderSettingsCard } from '@/ui/web/SiderAccountMenu';
import { WebPaneResizeHandle } from '@/ui/web/WebPaneResizeHandle';
import { chromeCssVars } from '@/ui/web/chrome-theme';
import { webColor, webLayout, webType } from '@/ui/web/theme';
import {
  ensureClaimedConversationsHydrated,
  getClaimedConversationsSnapshot,
  hasVisibleConversationProactiveHint,
  hasVisibleConversationRedDot,
  subscribeClaimedConversations,
} from '@/lib/claimed-conversations-store';

const { Sider, Content } = Layout;

type MenuKey = 'chat' | 'hosts' | 'annotators' | 'performance-settlement' | 'performance';

function resolveSelectedKey(pathname: string, listView: 'chat' | 'hosts' = 'chat'): MenuKey {
  if (pathname.includes('/annotators')) return 'annotators';
  if (pathname.includes('performance-settlement')) return 'performance-settlement';
  if (pathname.includes('performance') || pathname.includes('salary-details')) return 'performance';
  return listView === 'hosts' ? 'hosts' : 'chat';
}

function accountInitials(account: string): string {
  const text = account.trim();
  if (!text || text === '—') return '轻';
  if (/^[\u4e00-\u9fff]/.test(text)) return text.slice(0, 1);
  return text.slice(0, 2).toUpperCase();
}

function SiderAccountBar({
  open,
  onDuty,
  isSupervisor,
  onToggleDuty,
  dutyCooling,
}: {
  open: boolean;
  onDuty: boolean;
  isSupervisor: boolean;
  onToggleDuty: () => void;
  dutyCooling: boolean;
}) {
  const profile = useProfile();

  const account =
    profile.displayAccount !== '—'
      ? profile.displayAccount
      : getAgentAccount() || getUserInfo()?.agent_accout || '—';
  const agentId = profile.agentId || '—';
  const online = isSupervisor || onDuty;
  const initials = accountInitials(account);

  return (
    <Popover
      trigger="click"
      placement="topLeft"
      arrow={false}
      open={open}
      onOpenChange={(next) => {
        if (next) {
          if (getProfileModalView() === 'reset-password') return;
          openProfileModal('profile');
          void profile.loadUser();
          return;
        }
        if (getProfileModalView() === 'profile') closeProfileModal();
      }}
      classNames={{ root: 'qh-sider-settings' }}
      styles={{ container: { padding: 0 } }}
      content={
        <SiderSettingsCard
          account={account}
          agentId={agentId}
          role={profile.displayRole}
          phone={profile.displayPhone}
          dutyTime={profile.displayDutyTime}
          initials={initials}
          online={online}
          onDuty={onDuty}
          isSupervisor={isSupervisor}
          onToggleDuty={onToggleDuty}
          dutyCooling={dutyCooling}
        />
      }
    >
      <div
        role="button"
        tabIndex={0}
        className={`qh-sider-account${open ? ' is-open' : ''}`}
        title="设置"
        aria-label="打开设置"
        aria-expanded={open}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            (e.currentTarget as HTMLElement).click();
          }
        }}
      >
        <SettingOutlined />
        <span className="qh-sider-account-copy">
          <span className="qh-sider-account-name">设置</span>
        </span>
      </div>
    </Popover>
  );
}

function ChatNavIcon({ className, style }: { className?: string; style?: CSSProperties }) {
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

  const showDot = chatHasRedDot || chatHasYellowDot;
  const dotColor = chatHasRedDot ? webColor.danger : webColor.proactive;

  return (
    <span className={['qh-sider-chat-icon', className].filter(Boolean).join(' ')} style={style}>
      <MessageOutlined />
      {showDot ? <span className="qh-sider-chat-dot" style={{ background: dotColor }} /> : null}
    </span>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? '';
  const isSupervisor = getRole() === 'supervisor';
  const { onDuty, handleToggleDuty, dutyCooling } = useDutyControls();
  const { intakePaused, intakeLoading, intakeToggling, handleToggleIntake } = useIntakeControls();
  const [profileView, setProfileView] = useState(() => getProfileModalView());
  const [listView, setListView] = useState(getChatListView);
  const [actorBrand, setActorBrand] = useState<SiderActorBrand | null>(
    () => getSiderActorBrand() ?? hydrateSiderActorBrand(),
  );

  useEffect(() => subscribeProfileModal(setProfileView), []);
  useEffect(() => subscribeChatListView(setListView), []);
  useEffect(() => subscribeSiderActorBrand(setActorBrand), []);
  useEffect(() => {
    hydrateSiderActorBrand();
    return subscribeUserInfo(() => {
      hydrateSiderActorBrand();
    });
  }, []);
  const profileOpen = profileView === 'profile';

  const items: MenuProps['items'] = [
    {
      key: 'chat',
      icon: <ChatNavIcon />,
      label: '聊天',
    },
    {
      key: 'hosts',
      icon: <TeamOutlined />,
      label: '接待者',
    },
    ...(isSupervisor
      ? [
          { key: 'annotators' as const, icon: <TeamOutlined />, label: '标注员' },
          { key: 'performance-settlement' as const, icon: <CalculatorOutlined />, label: '绩效核算' },
        ]
      : [/*{ key: 'performance' as const, icon: <BarChartOutlined />, label: '绩效中心' }*/]),
  ];
  const chatItems = items.slice(0, 2);
  const restItems = items.slice(2);

  const onClick: MenuProps['onClick'] = ({ key }) => {
    closeProfileModal();
    if (key === 'chat') {
      setChatListView('chat');
      router.replace('/(tabs)/chat');
      return;
    }
    if (key === 'hosts') {
      setChatListView('hosts');
      router.replace('/(tabs)/chat');
      return;
    }
    if (key === 'annotators') router.replace('/(tabs)/annotators');
    else if (key === 'performance-settlement') router.replace('/(tabs)/performance-settlement');
    else if (key === 'performance') router.replace('/(tabs)/performance');
  };

  const selectedKey = resolveSelectedKey(pathname, listView);

  const siderStyle: CSSProperties = {
    height: '100vh',
    background: chromeCssVars.siderBg,
  };

  return (
    <Layout className="qh-web-shell" style={{ height: '100vh' }}>
      <Sider
        width={webLayout.siderWidth}
        theme="light"
        style={siderStyle}
      >
        <Flex
          vertical
          align="center"
          gap={8}
          className="qh-sider-brand"
        >
          {actorBrand ? (
            <div className="qh-sider-brand-actor">
              <Avatar
                className="qh-sider-brand-actor-avatar"
                src={actorBrand.faceURL || undefined}
                style={{
                  background: webColor.primary,
                  color: webColor.onPrimary,
                  border: 'none',
                  fontWeight: 600,
                }}
              >
                {(actorBrand.nickname || '?').trim().charAt(0) || '?'}
              </Avatar>
              <Flex vertical className="qh-sider-brand-actor-meta">
                <span className="qh-sider-brand-actor-name" title={actorBrand.nickname}>
                  {actorBrand.nickname}
                </span>
                <div className="qh-sider-qq-status-list">
                  <button
                    type="button"
                    className={`qh-sider-qq-status${isSupervisor || onDuty ? ' is-on' : ' is-off'}`}
                    disabled={isSupervisor}
                    aria-pressed={isSupervisor || onDuty}
                    aria-label={isSupervisor || onDuty ? '上班中' : '已下班，点击上班'}
                    title={isSupervisor || onDuty ? '上班中' : '点击上班'}
                    onClick={() => {
                      if (!isSupervisor) handleToggleDuty();
                    }}
                  >
                    <span className="qh-sider-qq-status-dot" aria-hidden />
                    <span>{isSupervisor || onDuty ? '上班' : '下班'}</span>
                  </button>
                  <button
                    type="button"
                    className={`qh-sider-qq-status${
                      (isSupervisor || onDuty) && !intakePaused
                        ? ' is-receiving'
                        : (isSupervisor || onDuty) && intakePaused
                          ? ' is-paused'
                          : ''
                    }`}
                    disabled={isSupervisor || !onDuty || intakeLoading || intakeToggling}
                    aria-pressed={(isSupervisor || onDuty) && !intakePaused}
                    aria-label={
                      !(isSupervisor || onDuty)
                        ? '已下班，无法接待'
                        : !intakePaused
                          ? '接待中'
                          : '已暂停接待，点击恢复'
                    }
                    title={
                      !(isSupervisor || onDuty)
                        ? '上班后可接待'
                        : !intakePaused
                          ? '接待中'
                          : '点击恢复接待'
                    }
                    onClick={() => {
                      if (!isSupervisor && onDuty) handleToggleIntake();
                    }}
                  >
                    <span className="qh-sider-qq-status-dot" aria-hidden />
                    <span>
                      {(isSupervisor || onDuty) && intakePaused ? '暂停' : '接待'}
                    </span>
                  </button>
                </div>
              </Flex>
            </div>
          ) : (
            <Typography.Title
              level={4}
              style={{
                ...webType.appName,
                width: '100%',
                minWidth: 0,
                margin: 0,
                textAlign: 'center',
              }}
            >
              {APP_NAME}
            </Typography.Title>
          )}
        </Flex>
        <Menu
          mode="inline"
          selectedKeys={[selectedKey]}
          items={chatItems}
          onClick={onClick}
          className="qh-sider-nav"
          style={{ borderInlineEnd: 'none' }}
        />
        {restItems.length > 0 ? (
          <Menu
            mode="inline"
            selectedKeys={[selectedKey]}
            items={restItems}
            onClick={onClick}
            className="qh-sider-nav qh-sider-nav-rest"
            style={{ borderInlineEnd: 'none' }}
          />
        ) : null}
        <SiderAccountBar
          open={profileOpen}
          onDuty={onDuty}
          isSupervisor={isSupervisor}
          onToggleDuty={handleToggleDuty}
          dutyCooling={dutyCooling && onDuty}
        />
        <WebPaneResizeHandle pane="sider" />
      </Sider>
      <Content
        className="qh-web-main"
        style={{ height: '100vh', minHeight: 0, minWidth: 0, overflow: 'hidden' }}
      >
        {children}
      </Content>
    </Layout>
  );
}
