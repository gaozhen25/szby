import { useCallback, useEffect, useRef, useState } from 'react';
import { login, registerAccount, sendAuthCode, formatAuthApiError } from '@/api/auth';
import { completeAuthFlow } from '@/core/auth-flow';
import { ApiError } from '@/lib/http';
import {
  sanitizeAccountInput,
  sanitizePasswordInput,
  sanitizePhoneInput,
  sanitizeSmsCodeInput,
  validateAccount,
  validateRegisterPassword,
  validatePhone,
  validateSmsCode,
  isPhoneValid,
} from '@/components/auth/credentials';

const SMS_COOLDOWN_SEC = 60;

export function useRegister() {
  const [account, setAccount] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [phone, setPhone] = useState('');
  const [smsCode, setSmsCode] = useState('');
  const [loading, setLoading] = useState(false);
  const [sendingCode, setSendingCode] = useState(false);
  const [cooldown, setCooldown] = useState(0);
  const [error, setError] = useState('');
  const cooldownTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => {
      if (cooldownTimerRef.current) clearInterval(cooldownTimerRef.current);
    };
  }, []);

  const startCooldown = useCallback(() => {
    setCooldown(SMS_COOLDOWN_SEC);
    if (cooldownTimerRef.current) clearInterval(cooldownTimerRef.current);
    cooldownTimerRef.current = setInterval(() => {
      setCooldown((prev) => {
        if (prev <= 1) {
          if (cooldownTimerRef.current) {
            clearInterval(cooldownTimerRef.current);
            cooldownTimerRef.current = null;
          }
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  }, []);

  const passwordMismatch =
    confirmPassword.length > 0 && password.length > 0 && password !== confirmPassword;

  const handleSendCode = async () => {
    setError('');
    const phoneErr = validatePhone(phone);
    if (phoneErr) {
      setError(phoneErr);
      return;
    }
    if (sendingCode || cooldown > 0) return;

    setSendingCode(true);
    try {
      await sendAuthCode({ phone_number: phone, purpose: 'register' });
      startCooldown();
    } catch (e) {
      setError(formatAuthApiError(e, '验证码发送失败，请稍后重试'));
    } finally {
      setSendingCode(false);
    }
  };

  const handleRegister = async () => {
    setError('');
    const accountErr = validateAccount(account);
    if (accountErr) {
      setError(accountErr);
      return;
    }
    const pwdErr = validateRegisterPassword(password);
    if (pwdErr) {
      setError(pwdErr);
      return;
    }
    if (password !== confirmPassword) {
      setError('两次输入的密码不一致');
      return;
    }
    const phoneErr = validatePhone(phone);
    if (phoneErr) {
      setError(phoneErr);
      return;
    }
    const codeErr = validateSmsCode(smsCode);
    if (codeErr) {
      setError(codeErr);
      return;
    }

    setLoading(true);
    try {
      await registerAccount({
        agent_accout: account,
        password,
        phone_number: phone,
        sms_code: smsCode,
      });
    } catch (e) {
      setError(formatAuthApiError(e, '注册失败，请稍后重试'));
      setLoading(false);
      return;
    }

    try {
      const res = await login({ identifier: account, password });
      await completeAuthFlow(res, account, password);
    } catch (e) {
      const detail =
        e instanceof ApiError
          ? (e.body as { detail?: string; message?: string } | null)?.detail ??
            (e.body as { detail?: string; message?: string } | null)?.message
          : undefined;
      if (detail === 'account_disabled') {
        setError('已注册成功，请联系管理员启用账号');
      } else {
        setError(formatAuthApiError(e, '注册成功，自动登录失败，请前往登录'));
      }
    } finally {
      setLoading(false);
    }
  };

  return {
    account,
    password,
    confirmPassword,
    phone,
    smsCode,
    loading,
    sendingCode,
    cooldown,
    error,
    passwordMismatch,
    canSendCode: !sendingCode && cooldown === 0 && isPhoneValid(phone),
    setAccount: (v: string) => {
      setAccount(sanitizeAccountInput(v));
      setError('');
    },
    setPassword: (v: string) => {
      setPassword(sanitizePasswordInput(v));
      setError('');
    },
    setConfirmPassword: (v: string) => {
      setConfirmPassword(sanitizePasswordInput(v));
      setError('');
    },
    setPhone: (v: string) => {
      setPhone(sanitizePhoneInput(v));
      setError('');
    },
    setSmsCode: (v: string) => {
      setSmsCode(sanitizeSmsCodeInput(v));
      setError('');
    },
    handleSendCode,
    handleRegister,
  };
}
