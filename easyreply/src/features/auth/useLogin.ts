import { useEffect, useState } from 'react';
import { login, formatAuthApiError } from '@/api/auth';
import { completeAuthFlow } from '@/core/auth-flow';
import { loadLoginCredentials } from '@/core/auth-persist';
import {
  sanitizeAccountInput,
  sanitizePasswordInput,
  validateAccount,
  validatePassword,
  isAccountValid,
  isPasswordValid,
} from '@/components/auth/credentials';

export function useLogin() {
  const [account, setAccount] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let alive = true;
    (async () => {
      const saved = await loadLoginCredentials();
      if (!alive || !saved) return;
      setAccount(sanitizeAccountInput(saved.identifier));
      setPassword(sanitizePasswordInput(saved.password));
    })();
    return () => {
      alive = false;
    };
  }, []);

  const handleLogin = async () => {
    setError('');
    const accountErr = validateAccount(account);
    if (accountErr) {
      setError(accountErr);
      return;
    }
    const pwdErr = validatePassword(password);
    if (pwdErr) {
      setError(pwdErr);
      return;
    }

    setLoading(true);
    try {
      const res = await login({ identifier: account, password });
      await completeAuthFlow(res, account, password);
    } catch (e) {
      setError(formatAuthApiError(e, '登录失败，请稍后重试'));
    } finally {
      setLoading(false);
    }
  };

  return {
    account,
    password,
    loading,
    error,
    canLogin: !loading && isAccountValid(account) && isPasswordValid(password),
    setAccount: (value: string) => {
      setAccount(sanitizeAccountInput(value));
      setError('');
    },
    setPassword: (value: string) => {
      setPassword(sanitizePasswordInput(value));
      setError('');
    },
    handleLogin,
  };
}
