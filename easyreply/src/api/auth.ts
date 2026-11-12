// ============================================================
// TMS Auth API（端口 10007）
// 文档：api_integration — /api/app/auth/*
// ============================================================

import { get, post, ApiError } from './client';
import { getAuthApiBaseUrl } from '@/lib/http';

const authConfig = { baseURL: () => getAuthApiBaseUrl(), noAuth: true as const };
const authGetConfig = { baseURL: () => getAuthApiBaseUrl() };

/** 登录请求：仅账号密码（不自动识别；手机号登录暂不开放） */
export interface LoginParams {
  login_type: 'account';
  identifier: string;
  password: string;
}

/** 发送短信验证码 */
export interface SendCodeParams {
  phone_number: string;
  purpose: 'register' | 'reset_password';
}

export interface SendCodeResult {
  ok: boolean;
}

/** 注册请求 */
export interface RegisterParams {
  agent_accout: string;
  password: string;
  phone_number: string;
  sms_code: string;
  role: 'agent' | 'supervisor';
  supervisor_agent_id: string | null;
  additional_info?: string;
  on_duty_time?: string;
}

export interface LoginResult {
  ok: boolean;
  token: string;
  agent_id: string;
  role: string;
  expires_in?: number;
}

export interface RegisterResult {
  ok: boolean;
  agent_id: string;
  agent_accout: string;
  role: string;
  valid: boolean;
  created_at: string;
}

export interface AgentInfo {
  agent_id: string;
  agent_accout: string;
  role: string;
  supervisor_agent_id: string | null;
  subordinate_agent_ids?: string[];
  valid: boolean;
  is_fallback?: boolean;
  max_active_cap?: number;
  domains?: string[];
  collected_actor_ids?: string[];
  /** 已收藏终端用户 Audience platform id 列表 */
  collected_audience_ids?: string[];
  additional_info?: string;
  on_duty_time?: string;
  phone_number?: string;
  created_at?: string;
  updated_at?: string;
}

export interface MeResult {
  ok: boolean;
  info: AgentInfo;
}

export interface ResetPasswordParams {
  phone_number: string;
  sms_code: string;
  new_password: string;
}

export interface ResetPasswordResult {
  ok: boolean;
  agent_id: string;
  updated_at: string;
}

const AUTH_ERROR_MAP: Record<string, string> = {
  invalid_credentials: '账号或密码错误',
  account_disabled: '账号未启用，请稍后重试',
  agent_accout_already_exists: '账号已存在',
  agent_accout_or_phone_number_already_exists: '账号或手机号已存在',
  invalid_or_expired_sms_code: '验证码错误或已失效，请重新获取',
  sms_code_resend_too_frequent: '发送过于频繁，请稍后再试',
  sms_send_failed: '短信发送失败，请稍后重试',
  sms_service_not_configured: '短信服务未配置',
  agent_not_found: '该手机号未绑定任何账号',
  invalid_token: '登录已失效，请重新登录',
  token_expired: '登录已过期，请重新登录',
  jwt_not_configured: '服务端鉴权未配置',
};

/** 解析 Auth / 通用 API 错误文案 */
export function formatAuthApiError(e: unknown, fallback = '请求失败，请稍后重试'): string {
  if (!(e instanceof ApiError)) return fallback;
  const body = e.body as { detail?: string; message?: string } | null;
  const detail = body?.detail ?? body?.message;
  if (typeof detail === 'string' && AUTH_ERROR_MAP[detail]) return AUTH_ERROR_MAP[detail];
  if (typeof detail === 'string' && detail) return detail;
  return e.message || fallback;
}

/** 账号密码登录 */
export function login(params: { identifier: string; password: string }): Promise<LoginResult> {
  const body: LoginParams = {
    login_type: 'account',
    identifier: params.identifier,
    password: params.password,
  };
  return post<LoginResult>('/api/app/auth/login', body, {
    baseURL: authConfig.baseURL(),
    noAuth: authConfig.noAuth,
  });
}

/** 发送短信验证码（无需 token） */
export function sendAuthCode(params: SendCodeParams): Promise<SendCodeResult> {
  return post<SendCodeResult>('/api/app/auth/send_code', params, {
    baseURL: authConfig.baseURL(),
    noAuth: authConfig.noAuth,
  });
}

/** 注册账号（固定 role=agent，supervisor_agent_id=unassigned） */
export function registerAccount(params: {
  agent_accout: string;
  password: string;
  phone_number: string;
  sms_code: string;
}): Promise<RegisterResult> {
  const body: RegisterParams = {
    agent_accout: params.agent_accout,
    password: params.password,
    phone_number: params.phone_number,
    sms_code: params.sms_code,
    role: 'agent',
    supervisor_agent_id: 'unassigned',
  };
  return post<RegisterResult>('/api/app/auth/register', body, {
    baseURL: authConfig.baseURL(),
    noAuth: authConfig.noAuth,
  });
}

/** 当前登录用户信息 */
export function fetchMe(): Promise<MeResult> {
  return get<MeResult>('/api/app/auth/me', undefined, {
    baseURL: authGetConfig.baseURL(),
  });
}

/** 通过手机号 + 短信验证码重置密码（无需 token） */
export function resetPassword(params: ResetPasswordParams): Promise<ResetPasswordResult> {
  return post<ResetPasswordResult>('/api/app/auth/reset_password', params, {
    baseURL: authConfig.baseURL(),
    noAuth: authConfig.noAuth,
  });
}
