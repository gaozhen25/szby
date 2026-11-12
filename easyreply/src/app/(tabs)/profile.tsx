// ============================================================
// 我的
// ============================================================
import { useCallback, useState, type ComponentType } from 'react';
import { Platform, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { router, useFocusEffect } from 'expo-router';
import Constants from 'expo-constants';

import { ScreenCanvas } from '@/components/UI/ScreenCanvas';
import { ScreenHeader } from '@/components/UI/ScreenHeader';
import { useTheme } from '@/design/theme-context';
import { Tokens } from '@/design/tokens';
import type { AgentInfo } from '@/api/auth';
import { clearToken, getAgentAccount, getRole, getUserInfo, isLoggedIn } from '@/core/auth';
import { refreshUserInfo } from '@/core/auth-flow';
import { stopIM } from '@/core/im';
import { teardownPushListeners } from '@/core/push';
import { copyText } from '@/lib/clipboard';
import { dutyOff } from '@/api/tasks';
import { getAgentId, getTenantId } from '@/core/im';
import { saveDutyState } from '@/core/duty';
import { appAlert } from '@/lib/app-alert';
import { sendSentryTestEvent } from '@/core/sentry';
import { clearLocalLogs, getLocalLogStats } from '@/core/logging';
import { promptExportLocalLogs } from '@/features/profile/prompt-export-local-logs';
import { APP_NAME } from '@/lib/api-host';
import { showToast } from '@/lib/app-toast';
import { clearInactiveClaimedConversations } from '@/lib/claimed-conversations-store';
import { clearChatMessagesCacheForConversations } from '@/chatMessage/message/chat-messages-cache';
import {
  CheckOutlined,
  ClearOutlined,
  ClockCircleOutlined,
  CloudDownloadOutlined,
  CopyOutlined,
  DeleteOutlined,
  ExportOutlined,
  InfoCircleOutlined,
  LockOutlined,
  PhoneOutlined,
  RightOutlined,
  UserOutlined,
} from '@/ui/antd-icons';

const appVersion =
  (Constants.expoConfig?.extra?.appVersion as string) ||
  Constants.expoConfig?.version ||
  '1.0.0';

const appName = APP_NAME;

function formatRole(role?: string): string {
  if (role === 'supervisor') return '主管';
  if (role === 'agent') return '客服';
  return role || '—';
}

/** 按字符断行（连续 ID 默认按「词」不换行） */
function breakByChar(text: string): string {
  return text.split('').join('\u200B');
}

function SettingsRow({
  icon: Icon,
  label,
  right,
  showChevron = true,
  onPress,
  isLast,
}: {
  icon: ComponentType<{ size?: number; color?: string }>;
  label: string;
  right?: string;
  showChevron?: boolean;
  onPress?: () => void;
  isLast?: boolean;
}) {
  const theme = useTheme();

  return (
    <>
      <Pressable
        style={({ pressed }) => [styles.settingsRow, pressed && onPress && { opacity: 0.75 }]}
        onPress={onPress}
        disabled={!onPress}
      >
        <View style={[styles.settingsIcon, { backgroundColor: theme.primarySoft }]}>
          <Icon size={16} color={theme.primary} />
        </View>
        <Text style={[styles.settingsLabel, { color: theme.text }]} numberOfLines={1}>
          {label}
        </Text>
        {right ? (
          <Text
            style={[styles.settingsRight, { color: theme.textSubtle }]}
            numberOfLines={1}
            adjustsFontSizeToFit
            minimumFontScale={0.85}
          >
            {right}
          </Text>
        ) : null}
        {showChevron ? (
          <RightOutlined
            size={16}
            color={theme.placeholder}
          />
        ) : null}
      </Pressable>
      {!isLast ? <View style={[styles.settingsDivider, { backgroundColor: theme.divider }]} /> : null}
    </>
  );
}

export default function ProfileScreen() {
  const theme = useTheme();
  const [user, setUser] = useState<AgentInfo | null>(() => getUserInfo());
  const [idCopied, setIdCopied] = useState(false);

  const loadUser = useCallback(async () => {
    if (!isLoggedIn()) return;
    setUser(getUserInfo());
    try {
      await refreshUserInfo();
      setUser(getUserInfo());
    } catch {
      setUser(getUserInfo());
    }
  }, []);

  useFocusEffect(useCallback(() => {
    void loadUser();
  }, [loadUser]));

  const displayAccount = user?.agent_accout ?? getAgentAccount() ?? '—';
  const displayRole = formatRole(user?.role);
  const displayPhone = user?.phone_number?.trim() || '—';
  const agentId = user?.agent_id ?? '';

  const handleCopyAgentId = useCallback(async () => {
    if (!agentId) return;
    const ok = await copyText(agentId);
    if (ok) {
      setIdCopied(true);
      setTimeout(() => setIdCopied(false), 60000);
    }
  }, [agentId]);

  const handleLogout = () => {
    // 退出登录：尽力通知服务端下班（失败不阻断登出）
    void dutyOff(getAgentId(), getTenantId()).catch(() => {});
    void saveDutyState(getAgentId(), false).catch(() => {});
    stopIM();
    clearToken();
    teardownPushListeners();
    router.replace('/login');
  };

  const handleLogoutPress = () => {
    const isSupervisor = (user?.role ?? getRole()) === 'supervisor';
    const message = isSupervisor
      ? '确定退出当前账号？'
      : '退出登录将同步下班，所有会话任务将被系统回收并重新分配，当前进行中的会话可能会分配给其他客服。确定退出吗？';
    appAlert('确认退出登录', message, [
      { text: '取消', style: 'cancel' },
      {
        text: '退出登录',
        style: 'destructive',
        onPress: handleLogout,
      },
    ]);
  };

  const handleAbout = () => {
    appAlert(
      `关于${appName}`,
      `${appName} v${appVersion}\n客服工作台，助力高效沟通与绩效管理。`,
    );
  };

  const handleCheckUpdate = () => {
    appAlert('检查更新', `当前已是最新版本 v${appVersion}`);
  };

  // 保留：与下方注释掉的「上报 Sentry 测试」入口配套
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const handleSentryProbe = () => {
    void (async () => {
      const result = await sendSentryTestEvent();
      appAlert(result.ok ? 'Sentry 测试' : 'Sentry 未发送', result.message);
    })();
  };

  const handleExportLocalLogs = () => {
    promptExportLocalLogs();
  };

  const handleClearLocalLogs = () => {
    void (async () => {
      const stats = await getLocalLogStats();
      appAlert(
        '清除本地日志',
        stats.fileCount > 0
          ? `将删除 ${stats.fileCount} 个日志文件（约 ${Math.ceil(stats.totalBytes / 1024)} KB），确认继续？`
          : '当前没有本地日志文件。',
        stats.fileCount > 0
          ? [
              { text: '取消', style: 'cancel' },
              {
                text: '清除',
                style: 'destructive',
                onPress: () => {
                  void clearLocalLogs()
                    .then(() => showToast('本地日志已清除', { variant: 'success' }))
                    .catch((e) =>
                      appAlert('清除失败', e instanceof Error ? e.message : '请稍后重试'),
                    );
                },
              },
            ]
          : [{ text: '知道了' }],
      );
    })();
  };

  const handleOpenResetPassword = () => {
    if (!user?.phone_number?.trim()) {
      const tip =
        user?.role === 'supervisor'
          ? '当前账号未绑定手机号，请联系管理员处理'
          : '当前账号未绑定手机号，请联系主管处理';
      appAlert('无法修改密码', tip);
      return;
    }
    router.push('/feature/profile/reset-password');
  };

  const handleClearConversationCache = () => {
    appAlert('清除缓存', '将删除置灰会话及其本地聊天记录，活跃会话不受影响，确认继续？', [
      { text: '取消', style: 'cancel' },
      {
        text: '清除',
        style: 'destructive',
        onPress: () => {
          void (async () => {
            try {
              const imIds = await clearInactiveClaimedConversations('profile_clear_inactive');
              await clearChatMessagesCacheForConversations(imIds, 'profile_clear_inactive');
              appAlert(
                '清除成功',
                imIds.length > 0
                  ? `已清除 ${imIds.length} 个置灰会话及其聊天记录`
                  : '当前没有可清除的置灰会话',
              );
            } catch (e) {
              appAlert('清除失败', e instanceof Error ? e.message : '请稍后重试');
            }
          })();
        },
      },
    ]);
  };

  return (
    <ScreenCanvas>
      <StatusBar style="dark" />
      <View style={styles.page}>
        <ScreenHeader
          embedded
          title="我的"
          style={styles.header}
        />

        <ScrollView
          style={styles.scroll}
          contentContainerStyle={styles.scrollContent}
          showsVerticalScrollIndicator={false}
          keyboardShouldPersistTaps="handled"
        >
          <View
            style={[
              styles.accountCard,
              { backgroundColor: theme.surface, borderColor: theme.border },
              Tokens.shadow.card,
            ]}
          >
            <View style={[styles.accountAvatar, { backgroundColor: theme.primary }]}>
              <UserOutlined size={22} color="#FFF" />
            </View>
            <View style={styles.accountBody}>
              <View style={styles.accountNameRow}>
                <Text
                  style={[styles.accountName, { color: theme.text }]}
                  numberOfLines={1}
                >
                  {displayAccount}
                </Text>
                <View style={[styles.roleBadge, { backgroundColor: theme.primarySoft }]}>
                  <Text style={[styles.roleBadgeText, { color: theme.primary }]}>
                    {displayRole}
                  </Text>
                </View>
              </View>
              <View style={styles.agentIdRow}>
                <Text
                  style={[styles.accountMeta, styles.agentIdText, { color: theme.textSubtle }]}
                  selectable
                >
                  ID: {agentId ? breakByChar(agentId) : '—'}
                </Text>
                {agentId ? (
                  <Pressable
                    onPress={handleCopyAgentId}
                    hitSlop={10}
                    style={styles.copyBtn}
                    accessibilityLabel="复制 ID"
                  >
                    {idCopied ? (
                      <CheckOutlined size={16} color={theme.primary} />
                    ) : (
                      <CopyOutlined size={16} color={theme.textSubtle} />
                    )}
                  </Pressable>
                ) : null}
              </View>
            </View>
          </View>

          <View
            style={[
              styles.settingsCard,
              { backgroundColor: theme.surface, borderColor: theme.border },
              Tokens.shadow.card,
            ]}
          >
            <SettingsRow icon={UserOutlined} label="角色" right={displayRole} showChevron={false} />
            <SettingsRow
              icon={PhoneOutlined}
              label="手机号"
              right={displayPhone}
              showChevron={false}
            />
            <SettingsRow
              icon={ClockCircleOutlined}
              label="上班时段"
              right={user?.on_duty_time || '24h'}
              showChevron={false}
            />
            <SettingsRow
              icon={LockOutlined}
              label="修改密码"
              onPress={handleOpenResetPassword}
              isLast
            />
          </View>

          <View
            style={[
              styles.settingsCard,
              { backgroundColor: theme.surface, borderColor: theme.border },
              Tokens.shadow.card,
            ]}
          >
            <SettingsRow
              icon={DeleteOutlined}
              label="清除缓存"
              onPress={handleClearConversationCache}
            />
            <SettingsRow
              icon={ExportOutlined}
              label="导出诊断日志"
              onPress={handleExportLocalLogs}
            />
            <SettingsRow
              icon={ClearOutlined}
              label="清除本地日志"
              onPress={handleClearLocalLogs}
              isLast
            />
          </View>

          <View
            style={[
              styles.settingsCard,
              { backgroundColor: theme.surface, borderColor: theme.border },
              Tokens.shadow.card,
            ]}
          >
            <SettingsRow icon={InfoCircleOutlined} label="关于" onPress={handleAbout} />
            <SettingsRow
              icon={CloudDownloadOutlined}
              label="检查更新"
              right={`v${appVersion}`}
              showChevron={false}
              onPress={handleCheckUpdate}
              isLast
            />
          </View>

          <Pressable
            style={[styles.logoutBtn, { backgroundColor: theme.primary }]}
            onPress={handleLogoutPress}
          >
            <Text style={styles.logoutText}>退出登录</Text>
          </Pressable>
        </ScrollView>
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
  header: {
    marginBottom: 20,
  },
  scroll: {
    flex: 1,
  },
  scrollContent: {
    paddingBottom: Tokens.spacing[8],
  },
  accountCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Tokens.spacing[4],
    borderRadius: Tokens.radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    padding: Tokens.spacing[4],
    marginBottom: 10,
  },
  accountAvatar: {
    width: 48,
    height: 48,
    borderRadius: 24,
    alignItems: 'center',
    justifyContent: 'center',
  },
  accountBody: {
    flex: 1,
    minWidth: 0,
    gap: 6,
  },
  accountNameRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    minWidth: 0,
  },
  accountName: {
    flexShrink: 1,
    minWidth: 0,
    fontSize: 20,
    fontWeight: '600',
    letterSpacing: 0.3,
  },
  roleBadge: {
    flexShrink: 0,
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: Tokens.radius.pill,
  },
  roleBadgeText: {
    fontSize: 12,
    fontWeight: '600',
  },
  accountMeta: {
    fontSize: 12,
  },
  agentIdRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 4,
    minWidth: 0,
  },
  agentIdText: {
    flex: 1,
    flexShrink: 1,
    minWidth: 0,
    lineHeight: 18,
    // web：强制按字符断行
    ...(Platform.OS === 'web' ? ({ wordBreak: 'break-all' } as object) : null),
  },
  copyBtn: {
    padding: 4,
    marginTop: -2,
    flexShrink: 0,
  },
  settingsCard: {
    borderRadius: Tokens.radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    overflow: 'hidden',
    marginBottom: 10,
  },
  settingsRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: Tokens.spacing[4],
    paddingVertical: 10,
    gap: Tokens.spacing[3],
    minHeight: 44,
  },
  settingsIcon: {
    width: 28,
    height: 28,
    borderRadius: 7,
    alignItems: 'center',
    justifyContent: 'center',
  },
  settingsLabel: {
    flex: 1,
    minWidth: 0,
    fontSize: 16,
    fontWeight: '400',
  },
  settingsRight: {
    flexShrink: 0,
    fontSize: 13,
    fontWeight: '500',
    fontVariant: ['tabular-nums'],
  },
  settingsChevron: {
    flexShrink: 0,
  },
  settingsDivider: {
    height: StyleSheet.hairlineWidth,
    marginLeft: Tokens.spacing[4] + 28 + Tokens.spacing[3],
  },
  logoutBtn: {
    height: 48,
    borderRadius: Tokens.radius.pill,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: Tokens.spacing[5],
  },
  logoutText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
  },
});
