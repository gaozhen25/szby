import { Stack, router, usePathname, type Href } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import Constants from 'expo-constants';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { ActivityIndicator, Platform, View } from 'react-native';

import { initSentry, wrapRoot } from '@/core/sentry';
import {
  initBootProfile,
  initLocalLogging,
  installAppErrorLogging,
  markBootPhase,
} from '@/core/logging';
import { ThemeProvider } from '@/design/theme-context';
import { getAuthApiBaseUrl, getChatApiBaseUrl, getImWsBaseUrl, APP_ENV, APP_NAME } from '@/lib/api-host';
import { getRole, getUserInfo } from '@/core/auth';
import { bootstrapAuthOnLaunch, ensureAuthIdentityOrLogin } from '@/core/auth-flow';
import { getAgentInfoById, getCachedAgentInfoById, warmAgentInfoCache } from '@/lib/agent-info';
import { appAlert } from '@/lib/app-alert';
import { webColor } from '@/ui/web/theme';
import type { IMGatewayEvent } from '@/core/im/types';

/**
 * Web 上把一段启动逻辑排到空闲时段，并单独成一个任务。
 *
 * 关键是「单独成一个任务」：以前 IM 与 Push 两个 chunk 的下载、编译、执行、连接
 * 全挤在同一个 requestIdleCallback 回调里，浏览器无法在中途插入输入事件，
 * 于是整段变成一个长任务。而 timeout 又保证它在页面一直繁忙时也会到点强制执行 ——
 * 刷新后 1~2 秒正好是用户开始打字的时刻，输入法组字就被这个长任务顶住。
 * 拆成各自独立的回调后，两段之间会让出主线程，输入事件得以及时处理。
 */
function runWhenIdle(phase: string, run: () => void, timeout: number): void {
  const task = () => {
    markBootPhase(phase);
    run();
  };
  if (typeof requestIdleCallback === 'function') {
    requestIdleCallback(task, { timeout });
  } else {
    setTimeout(task, 0);
  }
}

function scheduleInitSentry(): void {
  if (Platform.OS === 'web') {
    runWhenIdle('initSentry', () => initSentry(), 3000);
    return;
  }
  initSentry();
}

function scheduleDeferredRuntimeInit(): void {
  if (Platform.OS === 'web') {
    runWhenIdle(
      'initIM',
      () => {
        void import('@/core/im').then(({ initIM }) => initIM());
      },
      2000,
    );
    // 推送初始化对首屏交互无贡献，排到 IM 之后，且不与其同一个任务
    runWhenIdle(
      'initPush',
      () => {
        void import('@/core/push').then(({ initPushRuntime }) => initPushRuntime());
      },
      4000,
    );
    return;
  }
  void import('@/core/im').then(({ initIM }) => initIM());
  void import('@/core/push').then(({ initPushRuntime }) => initPushRuntime());
}

// 探针要最早装，才能观测到后续所有启动阶段的长任务
initBootProfile();
markBootPhase('模块加载');
scheduleInitSentry();
initLocalLogging();
installAppErrorLogging();
scheduleDeferredRuntimeInit();
// 尽早 hydrate，避免 Web 路由先渲染、各页 effect 带着空 agent_id 打接口
void bootstrapAuthOnLaunch();

const appVersion = (Constants.expoConfig?.extra?.appVersion as string) || '1.0.0';

console.log(`[${APP_NAME}] v${appVersion} · ${APP_ENV} · ${Platform.OS}`);
console.log('[Env] AUTH_API_URL :', getAuthApiBaseUrl() || 'NOT SET');
console.log('[Env] CHAT_API_URL:', getChatApiBaseUrl() || 'NOT SET');
console.log('[Env] IM_WS_URL    :', getImWsBaseUrl() || 'NOT SET');
console.log('[Env] JPUSH_APP_KEY:', process.env.EXPO_PUBLIC_JPUSH_APP_KEY ? '****configured****' : 'NOT SET');
console.log('[Env] SENTRY_DSN  :', process.env.EXPO_PUBLIC_SENTRY_DSN ? '****configured****' : 'NOT SET');

SplashScreen.preventAutoHideAsync();

function hideSplash(): void {
  SplashScreen.hideAsync().catch((e) => {
    console.warn('[Splash] hideAsync failed:', e);
  });
}

/**
 * 根启动逻辑（鉴权恢复 / IM 同步 / 上报弹窗）。
 * wrap / hosts 由原生与 Web 各自注入，避免 Web 把 antd 打进手机包。
 */
export function AppRootLayout({
  wrap,
  hosts,
}: {
  wrap: (content: ReactNode) => ReactNode;
  hosts: ReactNode;
}) {
  const lastTransferAlertAtRef = useRef(0);
  const [authReady, setAuthReady] = useState(Platform.OS === 'web');
  const pathname = usePathname() ?? '';

  useEffect(() => {
    void ensureAuthIdentityOrLogin(pathname);
  }, [pathname]);

  useEffect(() => {
    let alive = true;

    const finishBoot = () => {
      if (!alive) return;
      setAuthReady(true);
      hideSplash();
    };

    const afterAuth = () => {
      void import('@/core/push').then(({ bootstrapPush, promptWebDesktopNotificationIfNeeded }) => {
        void bootstrapPush();
        if (Platform.OS === 'web') {
          promptWebDesktopNotificationIfNeeded();
        }
      });
    };

    // Web：先渲染路由壳层，会话在后台 hydrate（入口页用 waitForAuthBootstrap 做分流）
    if (Platform.OS === 'web') {
      finishBoot();
      void (async () => {
        try {
          await bootstrapAuthOnLaunch();
          markBootPhase('auth bootstrap 完成');
          if (getRole() === 'supervisor') {
            warmAgentInfoCache(getUserInfo()?.subordinate_agent_ids ?? []);
          }
        } catch (e) {
          console.warn('[Auth] bootstrap failed', e);
        } finally {
          if (!alive) return;
          afterAuth();
        }
      })();
      return () => {
        alive = false;
      };
    }

    const fallback = setTimeout(finishBoot, 2500);

    void (async () => {
      try {
        await bootstrapAuthOnLaunch();
        if (getRole() === 'supervisor') {
          warmAgentInfoCache(getUserInfo()?.subordinate_agent_ids ?? []);
        }
      } catch (e) {
        console.warn('[Auth] bootstrap failed', e);
      } finally {
        if (!alive) return;
        clearTimeout(fallback);
        finishBoot();
        afterAuth();
      }
    })();

    return () => {
      alive = false;
      clearTimeout(fallback);
    };
  }, []);

  useEffect(() => {
    let alive = true;
    let offSync = () => {};
    let offIncomingAlert = () => {};
    let offTakeoverAlert = () => {};

    void import('@/lib/claimed-conversations-store').then((mod) => {
      if (!alive) return;
      markBootPhase('会话列表 sync 启动');
      offSync = mod.initClaimedConversationsSync();
      offTakeoverAlert = mod.subscribeSupervisorTakeoverAlert(({ actorName, audienceName }) => {
        const body = `你的会话「${actorName} → ${audienceName}」已被主管接管`;
        appAlert('会话已被接管', body, [{ text: '知道了' }]);
      });
    });
    void import('@/core/push').then(({ initIncomingMessageAlert }) => {
      if (!alive) return;
      offIncomingAlert = initIncomingMessageAlert();
    });

    return () => {
      alive = false;
      offTakeoverAlert();
      offIncomingAlert();
      offSync();
    };
  }, []);

  useEffect(() => {
    let off: (() => void) | undefined;
    let alive = true;

    void import('@/core/im').then(({ getChatService }) => {
      if (!alive) return;
      const chat = getChatService();
      off = chat.onGatewayEvent((evt: IMGatewayEvent) => {
      const e = evt as any;
      const p = e?.payload ?? e;
      const t = e?.type ?? p?.type;
      if (t !== 'transfer_reported') return;

      const role = getRole();
      if (role !== 'supervisor') {
        console.warn('[TransferReported] 当前角色非 supervisor，跳过弹窗', { role });
        return;
      }

      const taskID: string | undefined =
        e?.taskID ?? p?.taskID ?? e?.task_id ?? p?.task_id ?? e?.task_context?.taskID ?? p?.task_context?.taskID;
      const fromAgentId: string | undefined =
        e?.fromAgentId ?? p?.fromAgentId ?? e?.from_agent_id ?? p?.from_agent_id;
      const reason: string | undefined = e?.reason ?? p?.reason;
      if (!taskID || !fromAgentId) {
        console.warn('[TransferReported] 缺少 taskID/fromAgentId，跳过弹窗', {
          taskID,
          fromAgentId,
          keys: e && typeof e === 'object' ? Object.keys(e) : [],
        });
        return;
      }

      const now = Date.now();
      if (now - lastTransferAlertAtRef.current < 1500) return;
      lastTransferAlertAtRef.current = now;

      const go = () =>
        router.push({
          pathname: '/chat/[id]',
          params: { id: taskID, supervisor: '1', annotatorId: fromAgentId },
        } as unknown as Href);

      const showAlert = (agentAccount: string) => {
        const body = reason?.trim()
          ? `客服「${agentAccount}」上报了消息\n\n原因：${reason.trim()}`
          : `客服「${agentAccount}」上报了消息`;
        appAlert('新的客服上报', body, [
          { text: '稍后', style: 'cancel' },
          { text: '查看消息', onPress: go },
        ]);
      };

      const cached = getCachedAgentInfoById(fromAgentId)?.agent_accout?.trim();
      if (cached) {
        showAlert(cached);
        return;
      }

      void (async () => {
        let agentAccount = fromAgentId;
        try {
          const agentInfo = await Promise.race([
            getAgentInfoById(fromAgentId).catch(() => null),
            new Promise<null>((resolve) => setTimeout(() => resolve(null), 5000)),
          ]);
          const account = agentInfo?.agent_accout?.trim();
          if (account) agentAccount = account;
          else console.warn('[TransferReported] 未取到 agent_accout，回退展示 agent_id', { fromAgentId });
        } catch {
          // ignore
        }
        showAlert(agentAccount);
      })();
      });
    });

    return () => {
      alive = false;
      off?.();
    };
  }, []);

  if (!authReady) {
    if (Platform.OS === 'web') {
      return (
        <View
          style={{
            flex: 1,
            alignItems: 'center',
            justifyContent: 'center',
            backgroundColor: webColor.bg,
          }}
        >
          <ActivityIndicator size="large" color={webColor.primary} />
        </View>
      );
    }
    return null;
  }

  return (
    <ThemeProvider>
      {wrap(
        <>
          <Stack>
            <Stack.Screen name="index" options={{ headerShown: false }} />
            <Stack.Screen name="login" options={{ headerShown: false, animation: 'fade' }} />
            <Stack.Screen name="register" options={{ headerShown: false, animation: 'slide_from_right' }} />
            <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
            <Stack.Screen name="chat/[id]" options={{ headerShown: false }} />
            <Stack.Screen name="feature/performance/salary-details" options={{ headerShown: false }} />
            <Stack.Screen name="feature/profile/reset-password" options={{ headerShown: false }} />
            <Stack.Screen name="feature/chat/actor-info/[id]" options={{ headerShown: false }} />
            <Stack.Screen name="feature/chat/my-favorites" options={{ headerShown: false }} />
            <Stack.Screen name="feature/chat/custom-stickers" options={{ headerShown: false }} />
            <Stack.Screen name="feature/annotators/[agentId]/sessions" options={{ headerShown: false }} />
            <Stack.Screen name="feature/annotators/[agentId]/assign-actors" options={{ headerShown: false }} />
          </Stack>
          {hosts}
        </>,
      )}
    </ThemeProvider>
  );
}

export { wrapRoot };
