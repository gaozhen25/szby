// ============================================================
// 认证持久化
// - 会话（token）：杀进程后恢复，实现自动登录
// - 凭证（账号密码）：退出登录后仍保留，供登录页自动填充
// ============================================================
import AsyncStorage from '@react-native-async-storage/async-storage';
import type { AgentInfo } from '@/api/auth';

const SESSION_KEY = 'auth_session_v1';
const CREDENTIALS_KEY = 'auth_credentials_v1';

export type PersistedAuthSession = {
  version: 1;
  token: string;
  tokenType: string;
  agentId: string;
  agentAccount: string | null;
  role: string | null;
  userInfo: AgentInfo | null;
};

export type PersistedLoginCredentials = {
  version: 1;
  identifier: string;
  password: string;
};

export async function saveAuthSession(session: Omit<PersistedAuthSession, 'version'>): Promise<void> {
  try {
    const payload: PersistedAuthSession = { version: 1, ...session };
    await AsyncStorage.setItem(SESSION_KEY, JSON.stringify(payload));
  } catch (e) {
    console.warn('[AuthPersist] 保存会话失败', e);
  }
}

export async function loadAuthSession(): Promise<PersistedAuthSession | null> {
  try {
    const raw = await AsyncStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<PersistedAuthSession> | null;
    if (!parsed || parsed.version !== 1 || !parsed.token?.trim() || !parsed.agentId?.trim()) {
      await AsyncStorage.removeItem(SESSION_KEY);
      return null;
    }
    return {
      version: 1,
      token: parsed.token.trim(),
      tokenType: parsed.tokenType?.trim() || 'Bearer',
      agentId: parsed.agentId.trim(),
      agentAccount: parsed.agentAccount ?? null,
      role: parsed.role ?? null,
      userInfo: parsed.userInfo ?? null,
    };
  } catch (e) {
    console.warn('[AuthPersist] 读取会话失败', e);
    return null;
  }
}

export async function clearAuthSession(): Promise<void> {
  try {
    await AsyncStorage.removeItem(SESSION_KEY);
  } catch (e) {
    console.warn('[AuthPersist] 清除会话失败', e);
  }
}

export async function saveLoginCredentials(identifier: string, password: string): Promise<void> {
  const id = identifier.trim();
  if (!id || !password) return;
  try {
    const payload: PersistedLoginCredentials = {
      version: 1,
      identifier: id,
      password,
    };
    await AsyncStorage.setItem(CREDENTIALS_KEY, JSON.stringify(payload));
  } catch (e) {
    console.warn('[AuthPersist] 保存登录凭证失败', e);
  }
}

export async function loadLoginCredentials(): Promise<PersistedLoginCredentials | null> {
  try {
    const raw = await AsyncStorage.getItem(CREDENTIALS_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<PersistedLoginCredentials> | null;
    if (!parsed || parsed.version !== 1 || !parsed.identifier?.trim() || !parsed.password) {
      return null;
    }
    return {
      version: 1,
      identifier: parsed.identifier.trim(),
      password: parsed.password,
    };
  } catch (e) {
    console.warn('[AuthPersist] 读取登录凭证失败', e);
    return null;
  }
}
