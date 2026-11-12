// ============================================================
// API 主机解析
// .env 配置各环境 Base URL：
//   test       → EXPO_PUBLIC_API_HOST_TEST（http：Auth:10007 / 聊天+WS:10008）
//   production → EXPO_PUBLIC_API_HOST_PROD（正式服不加端口）
//                Auth(10007) → /tms
//                聊天(10008) → /tagmanager
//                WS(10008) → /tagmanager/ws/events
// 打包时由 EXPO_PUBLIC_APP_ENV=test|production 选择对应地址
// Web：.env 被 gitignore，浏览器拿不到 EXPO_PUBLIC_API_HOST*，因此必须有源码默认主机。
// ============================================================
import Constants from 'expo-constants';
import { PUBLIC_API_HOSTS } from '@/lib/public-api-hosts';

const AUTH_PORT = '10007';
const CHAT_PORT = '10008';
const WS_PATH = '/ws/events';
/** 正式服：对应测试服 10007 */
const PROD_AUTH_PATH = '/tms';
/** 正式服：对应测试服 10008 */
const PROD_CHAT_PATH = '/tagmanager';

export const APP_ENV =
  process.env.EXPO_PUBLIC_APP_ENV?.trim() ||
  'production';

/** 与 pnpm `:test` / `:prod` 脚本一致，不依赖可能过期的 Constants.expoConfig */
export const APP_NAME = APP_ENV === 'test' ? '轻回测试' : '轻回';

/** 正式环境（production）：HTTP/WS 均不追加自定义端口 */
export const isProductionEnv = APP_ENV === 'production';

const API_HOSTS: Record<string, string | undefined> = {
  development: process.env.EXPO_PUBLIC_API_HOST,
  test: process.env.EXPO_PUBLIC_API_HOST_TEST ?? process.env.EXPO_PUBLIC_API_HOST,
  production: process.env.EXPO_PUBLIC_API_HOST_PROD,
};

/** 旧版完整 URL 配置（未设置 EXPO_PUBLIC_API_HOST* 时回退） */
const LEGACY_AUTH_URLS: Record<string, string | undefined> = {
  development: process.env.EXPO_PUBLIC_AUTH_API_BASE_URL,
  test:
    process.env.EXPO_PUBLIC_AUTH_API_BASE_URL_TEST ??
    process.env.EXPO_PUBLIC_AUTH_API_BASE_URL,
  production:
    process.env.EXPO_PUBLIC_AUTH_API_BASE_URL_PROD ??
    process.env.EXPO_PUBLIC_AUTH_API_BASE_URL,
};

const LEGACY_CHAT_URLS: Record<string, string | undefined> = {
  development: process.env.EXPO_PUBLIC_API_BASE_URL,
  test:
    process.env.EXPO_PUBLIC_API_BASE_URL_TEST ??
    process.env.EXPO_PUBLIC_API_BASE_URL,
  production:
    process.env.EXPO_PUBLIC_API_BASE_URL_PROD ??
    process.env.EXPO_PUBLIC_API_BASE_URL,
};

const LEGACY_WS_URLS: Record<string, string | undefined> = {
  development: process.env.EXPO_PUBLIC_IM_WS_URL,
  test:
    process.env.EXPO_PUBLIC_IM_WS_URL_TEST ??
    process.env.EXPO_PUBLIC_IM_WS_URL,
  production:
    process.env.EXPO_PUBLIC_IM_WS_URL_PROD ??
    process.env.EXPO_PUBLIC_IM_WS_URL,
};

function normalizeHostInput(raw: string): URL {
  const trimmed = raw.trim();
  const withScheme = /^https?:\/\//i.test(trimmed) ? trimmed : `http://${trimmed}`;
  return new URL(withScheme);
}

/** 去掉末尾多余斜杠，保留路径前缀 */
function originWithPath(u: URL): string {
  const path = u.pathname.replace(/\/+$/, '');
  return path && path !== '/' ? `${u.origin}${path}` : u.origin;
}

/**
 * 正式服：不加端口，按服务类型挂路径（10007→/tms，10008→/tagmanager）
 * 测试服：按服务类型追加 10007 / 10008
 */
function buildServiceBase(host: string, port: string): string {
  const u = normalizeHostInput(host);
  if (isProductionEnv) {
    u.port = '';
    const path = port === AUTH_PORT ? PROD_AUTH_PATH : PROD_CHAT_PATH;
    return `${u.origin}${path}`;
  }
  u.port = port;
  return originWithPath(u);
}

function buildWsUrl(host: string): string {
  const u = normalizeHostInput(host);
  if (isProductionEnv) {
    // 正式服：与聊天同属 10008 → /tagmanager/ws/events
    const protocol = u.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${protocol}//${u.hostname}${PROD_CHAT_PATH}${WS_PATH}`;
  }
  u.protocol = u.protocol === 'https:' ? 'wss:' : 'ws:';
  u.port = CHAT_PORT;
  u.pathname = WS_PATH;
  return `${u.protocol}//${u.host}${u.pathname}`;
}

function resolveLegacy(
  legacy: Record<string, string | undefined>,
): string | undefined {
  return legacy[APP_ENV]?.trim() || undefined;
}

function extraApiHost(): string {
  const extra = Constants.expoConfig?.extra as { apiHost?: string } | undefined;
  return extra?.apiHost?.trim() ?? '';
}

/** 当前环境配置的主机（可含路径；正式服路径会被服务映射覆盖） */
export function getApiHost(): string {
  return (
    (API_HOSTS[APP_ENV] ?? API_HOSTS.production)?.trim() ||
    extraApiHost() ||
    PUBLIC_API_HOSTS[APP_ENV] ||
    PUBLIC_API_HOSTS.production
  );
}

/** Auth 服务 Base URL（登录/注册） */
export function getAuthApiBaseUrl(): string {
  const legacy = resolveLegacy(LEGACY_AUTH_URLS);
  if (legacy) return legacy;

  const host = getApiHost();
  if (!host) return `http://127.0.0.1:${AUTH_PORT}`;
  return buildServiceBase(host, AUTH_PORT);
}

/** 聊天/任务 HTTP Base URL */
export function getChatApiBaseUrl(): string {
  const legacy = resolveLegacy(LEGACY_CHAT_URLS);
  if (legacy) return legacy;

  const host = getApiHost();
  if (!host) return `http://127.0.0.1:${CHAT_PORT}`;
  return buildServiceBase(host, CHAT_PORT);
}

/** IM WebSocket Base URL */
export function getImWsBaseUrl(): string {
  const legacy = resolveLegacy(LEGACY_WS_URLS);
  if (legacy) return legacy;

  const host = getApiHost();
  if (!host) return `ws://127.0.0.1:${CHAT_PORT}${WS_PATH}`;
  return buildWsUrl(host);
}
