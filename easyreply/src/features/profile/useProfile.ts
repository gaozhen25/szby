import { useCallback, useState } from 'react';
import { router, useFocusEffect } from 'expo-router';
import Constants from 'expo-constants';
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
import { closeProfileModal } from '@/lib/profile-modal-bus';
import { sendSentryTestEvent } from '@/core/sentry';
import { clearLocalLogs, getLocalLogStats } from '@/core/logging';
import { promptExportLocalLogs } from '@/features/profile/prompt-export-local-logs';
import { APP_NAME } from '@/lib/api-host';
import { showToast } from '@/lib/app-toast';
import { clearInactiveClaimedConversations } from '@/lib/claimed-conversations-store';
import { clearChatMessagesCacheForConversations } from '@/chatMessage/message/chat-messages-cache';

const appVersion =
  (Constants.expoConfig?.extra?.appVersion as string) ||
  Constants.expoConfig?.version ||
  '1.0.0';

function formatRole(role?: string): string {
  if (role === 'supervisor') return '主管';
  if (role === 'agent') return '客服';
  return role || '—';
}

export function useProfile() {
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

  useFocusEffect(
    useCallback(() => {
      void loadUser();
    }, [loadUser]),
  );

  const displayAccount = user?.agent_accout ?? getAgentAccount() ?? '—';
  const displayRole = formatRole(user?.role);
  const displayPhone = user?.phone_number?.trim() || '—';
  const displayDutyTime = user?.on_duty_time?.trim() || '24h';
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
    closeProfileModal();
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
      { text: '退出登录', style: 'destructive', closeWithoutAnimation: true, onPress: handleLogout },
    ]);
  };

  const handleAbout = () => {
    appAlert(`关于${APP_NAME}`, `${APP_NAME} v${appVersion}\n客服工作台，助力高效沟通与绩效管理。`);
  };

  const handleCheckUpdate = () => {
    appAlert('检查更新', `当前已是最新版本 v${appVersion}`);
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

  const handleSentryProbe = () => {
    void (async () => {
      const result = await sendSentryTestEvent();
      appAlert(result.ok ? 'Sentry 测试' : 'Sentry 未发送', result.message);
    })();
  };

  const tryOpenResetPassword = useCallback((): boolean => {
    if (!user?.phone_number?.trim()) {
      const tip =
        user?.role === 'supervisor'
          ? '当前账号未绑定手机号，请联系管理员处理'
          : '当前账号未绑定手机号，请联系主管处理';
      appAlert('无法修改密码', tip);
      return false;
    }
    return true;
  }, [user?.phone_number, user?.role]);

  const handleOpenResetPassword = useCallback(() => {
    if (!tryOpenResetPassword()) return;
    router.push('/feature/profile/reset-password');
  }, [tryOpenResetPassword]);

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

  return {
    user,
    displayAccount,
    displayRole,
    displayPhone,
    displayDutyTime,
    agentId,
    idCopied,
    appName: APP_NAME,
    appVersion,
    handleCopyAgentId,
    handleLogoutPress,
    handleAbout,
    handleCheckUpdate,
    handleExportLocalLogs,
    handleClearLocalLogs,
    handleSentryProbe,
    handleOpenResetPassword,
    tryOpenResetPassword,
    loadUser,
    handleClearConversationCache,
  };
}
