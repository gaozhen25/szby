// ============================================================
// 网络请求工具模块
// 封装 fetch，支持 GET / POST / PUT / PATCH / DELETE
// 自动附加 Bearer Token（登录态）
// Base URL 根据 EXPO_PUBLIC_APP_ENV 自动切换：test / production（默认 production）
// 主机在 .env 配置 EXPO_PUBLIC_API_HOST*，端口由 api-host 按服务类型解析
// ============================================================
import { getAuthHeader, isLoggedIn } from '../core/auth';
import { APP_ENV, getAuthApiBaseUrl, getChatApiBaseUrl } from './api-host';
import { handleAuthExpired, isTokenExpiredBody } from '@/lib/auth-expiry';
import { captureHttpError } from '@/core/sentry';
import { logHttp } from '@/core/logging';

export { getAuthApiBaseUrl, getChatApiBaseUrl } from './api-host';

// ======== 类型定义 ========

/** HTTP 请求方法 */
export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

/** 请求配置 */
export interface RequestConfig {
  headers?: Record<string, string>;
  /** 超时时间（毫秒）；默认 15000；传 0 表示不限制 */
  timeout?: number;
  /** 是否跳过 Token 附加 */
  noAuth?: boolean;
  /** 自定义 baseURL（覆盖全局配置） */
  baseURL?: string;
}

/** API 错误类型 */
export class ApiError extends Error {
  status: number;
  body: unknown;
  path: string;

  constructor(status: number, body: unknown, path: string) {
    let msg = `Request failed: ${status}`;
    if (status === 413) {
      // 网关/后台拒绝超限请求体；body 常为 HTML，无 JSON message
      msg = '文件不能超过 50MB，请压缩后重试';
    } else if (typeof body === 'object' && body !== null) {
      const o = body as { message?: string; detail?: string };
      if (typeof o.detail === 'string' && o.detail) msg = o.detail;
      else if (typeof o.message === 'string' && o.message) msg = o.message;
    }
    super(msg);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
    this.path = path;
  }
}

/** 5xx / 网络失败上报；4xx（含 401）属于预期业务错误，不上报 */
function reportUnexpectedHttpError(error: ApiError): void {
  if (error.status >= 500 || error.status === 0) {
    captureHttpError(error, { path: error.path, status: error.status });
  }
}

function logHttpExchange(params: {
  method: string;
  path: string;
  status?: number;
  req?: unknown;
  res?: unknown;
  error?: string;
  startedAt: number;
}): void {
  try {
    logHttp({
      method: params.method,
      path: params.path,
      status: params.status,
      req: params.req,
      res: params.res,
      error: params.error,
      durationMs: Math.max(0, Date.now() - params.startedAt),
    });
  } catch {
    /* 日志失败不影响业务 */
  }
}

/** 上传/请求失败时给用户看的文案 */
export function getHttpErrorMessage(e: unknown, fallback = '请稍后重试'): string {
  if (e instanceof ApiError) return e.message || fallback;
  if (e instanceof Error && e.message.trim()) return e.message;
  return fallback;
}

// ======== 环境感知 Base URL ========

/** 当前环境的聊天/任务 HTTP Base URL */
const API_BASE_URL: string = getChatApiBaseUrl();

console.log(`[API] env=${APP_ENV}  chat=${API_BASE_URL}  auth=${getAuthApiBaseUrl()}`);

// ======== 内部工具 ========

function buildURL(path: string, params?: Record<string, string>, baseURL?: string): string {
  const base = baseURL || API_BASE_URL;
  const url = `${base.replace(/\/+$/, '')}/${path.replace(/^\/+/, '')}`;

  if (!params || Object.keys(params).length === 0) return url;

  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null) {
      searchParams.append(key, value);
    }
  });

  const qs = searchParams.toString();
  return qs ? `${url}?${qs}` : url;
}

function buildHeaders(
  customHeaders?: Record<string, string>,
  noAuth?: boolean,
): Record<string, string> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
    ...customHeaders,
  };

  if (!noAuth && isLoggedIn()) {
    const authHeader = getAuthHeader();
    if (authHeader) {
      headers['Authorization'] = authHeader;
    }
  }

  return headers;
}

async function fetchWithTimeout(
  url: string,
  init: RequestInit,
  timeout: number = 60000,
): Promise<Response> {
  if (timeout <= 0) {
    try {
      return await fetch(url, init);
    } catch (e) {
      const message =
        e instanceof Error && e.message.trim()
          ? e.message
          : 'Network request failed';
      const networkError = new ApiError(0, { message }, url);
      reportUnexpectedHttpError(networkError);
      throw networkError;
    }
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  try {
    const response = await fetch(url, { ...init, signal: controller.signal });
    return response;
  } catch (e) {
    if (e instanceof Error && e.name === 'AbortError') {
      const timeoutError = new ApiError(0, { message: `Request timeout: ${timeout}ms` }, url);
      reportUnexpectedHttpError(timeoutError);
      throw timeoutError;
    }
    // 断网 / DNS / CORS 等：统一 ApiError，避免 Uncaught TypeError: Failed to fetch
    const message =
      e instanceof Error && e.message.trim()
        ? e.message
        : 'Network request failed';
    const networkError = new ApiError(0, { message }, url);
    reportUnexpectedHttpError(networkError);
    throw networkError;
  } finally {
    clearTimeout(timeoutId);
  }
}

async function handleResponse<T>(
  response: Response,
  path: string,
  meta: { method: string; req?: unknown; startedAt: number },
): Promise<T> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = null;
  }

  // 全局拦截：登录失效（任意状态码返回 { detail: "token_expired" }）
  if (isTokenExpiredBody(body)) {
    handleAuthExpired();
  }

  if (!response.ok) {
    const error = new ApiError(response.status, body, path);
    logHttpExchange({
      method: meta.method,
      path,
      status: response.status,
      req: meta.req,
      res: body,
      error: error.message,
      startedAt: meta.startedAt,
    });
    reportUnexpectedHttpError(error);
    throw error;
  }

  logHttpExchange({
    method: meta.method,
    path,
    status: response.status,
    req: meta.req,
    res: body,
    startedAt: meta.startedAt,
  });
  return body as T;
}

// ======== 核心请求 ========

async function request<T = unknown>(
  method: HttpMethod,
  path: string,
  body?: unknown,
  config?: RequestConfig,
): Promise<T> {
  const { headers, timeout = 60000, noAuth = false, baseURL } = config || {};
  const startedAt = Date.now();

  const url = buildURL(path, undefined, baseURL);
  const requestHeaders = buildHeaders(headers, noAuth);

  const init: RequestInit = { method, headers: requestHeaders };
  if (body && method !== 'GET') {
    init.body = JSON.stringify(body);
  }

  try {
    const response = await fetchWithTimeout(url, init, timeout);
    return await handleResponse<T>(response, path, { method, req: body, startedAt });
  } catch (e) {
    if (e instanceof ApiError && e.status === 0) {
      logHttpExchange({
        method,
        path,
        status: 0,
        req: body,
        error: e.message,
        startedAt,
      });
    }
    throw e;
  }
}

// ======== 公开方法 ========

/** GET 请求 */
export async function get<T = unknown>(
  path: string,
  params?: Record<string, string>,
  config?: RequestConfig,
): Promise<T> {
  const { baseURL, ...rest } = config || {};
  const url = buildURL(path, params, baseURL);
  const headers = buildHeaders(rest?.headers, rest?.noAuth);
  const timeout = rest?.timeout ?? 60000;
  const startedAt = Date.now();

  try {
    const response = await fetchWithTimeout(url, { method: 'GET', headers }, timeout);
    return await handleResponse<T>(response, path, {
      method: 'GET',
      req: params,
      startedAt,
    });
  } catch (e) {
    if (e instanceof ApiError && e.status === 0) {
      logHttpExchange({
        method: 'GET',
        path,
        status: 0,
        req: params,
        error: e.message,
        startedAt,
      });
    }
    throw e;
  }
}

/** POST 请求 */
export async function post<T = unknown>(
  path: string,
  body?: unknown,
  config?: RequestConfig,
): Promise<T> {
  return request<T>('POST', path, body, config);
}

/** PUT 请求 */
export async function put<T = unknown>(
  path: string,
  body?: unknown,
  config?: RequestConfig,
): Promise<T> {
  return request<T>('PUT', path, body, config);
}

/** PATCH 请求 */
export async function patch<T = unknown>(
  path: string,
  body?: unknown,
  config?: RequestConfig,
): Promise<T> {
  return request<T>('PATCH', path, body, config);
}

/** DELETE 请求 */
export async function del<T = unknown>(
  path: string,
  body?: unknown,
  config?: RequestConfig,
): Promise<T> {
  return request<T>('DELETE', path, body, config);
}

/** 上传文件（FormData）；默认不限制超时（timeout=0） */
export async function upload<T = unknown>(
  path: string,
  formData: FormData,
  config?: RequestConfig,
): Promise<T> {
  const { timeout = 0, noAuth = false, baseURL } = config || {};
  const url = buildURL(path, undefined, baseURL);
  const startedAt = Date.now();
  const reqSummary = { formData: true };

  const headers: Record<string, string> = {
    'Accept': 'application/json',
    ...(config?.headers || {}),
  };

  if (!noAuth && isLoggedIn()) {
    const authHeader = getAuthHeader();
    if (authHeader) headers['Authorization'] = authHeader;
  }

  try {
    const response = await fetchWithTimeout(url, {
      method: 'POST',
      headers,
      body: formData,
      // @ts-expect-error duplex required for streaming uploads
      duplex: 'half',
    }, timeout);

    return await handleResponse<T>(response, path, {
      method: 'POST',
      req: reqSummary,
      startedAt,
    });
  } catch (e) {
    if (e instanceof ApiError && e.status === 0) {
      logHttpExchange({
        method: 'POST',
        path,
        status: 0,
        req: reqSummary,
        error: e.message,
        startedAt,
      });
    }
    throw e;
  }
}

const api = { get, post, put, patch, del, delete: del, upload, ApiError };
export default api;
