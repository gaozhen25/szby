import { useCallback, useEffect, useRef, useState } from 'react';
import { router } from 'expo-router';
import { formatAuthApiError, resetPassword, sendAuthCode } from '@/api/auth';
import { getUserInfo } from '@/core/auth';
import { appAlert } from '@/lib/app-alert';
import {
  isPhoneValid,
  isRegisterPasswordValid,
  isSmsCodeValid,
  sanitizePasswordInput,
  sanitizePhoneInput,
  sanitizeSmsCodeInput,
  validatePhone,
  validateRegisterPassword,
  validateSmsCode,
} from '@/components/auth/credentials';

const SMS_COOLDOWN_SEC = 60;

export function useResetPassword(opts?: { onSuccess?: () => void }) {
  const boundPhone = getUserInfo()?.phone_number?.trim() || '';
  const [phone, setPhone] = useState(boundPhone);
  const [smsCode, setSmsCode] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
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
      await sendAuthCode({ phone_number: phone, purpose: 'reset_password' });
      startCooldown();
    } catch (e) {
      setError(formatAuthApiError(e, '验证码发送失败，请稍后重试'));
    } finally {
      setSendingCode(false);
    }
  };

  const handleSubmit = async () => {
    setError('');
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
    const pwdErr = validateRegisterPassword(password);
    if (pwdErr) {
      setError(pwdErr);
      return;
    }
    if (password !== confirmPassword) {
      setError('两次输入的密码不一致');
      return;
    }
    setLoading(true);
    try {
      await resetPassword({
        phone_number: phone,
        sms_code: smsCode,
        new_password: password,
      });
      appAlert('修改成功', '密码已更新，请使用新密码登录', [
        { text: '知道了', onPress: () => opts?.onSuccess?.() ?? router.back() },
      ]);
    } catch (e) {
      setError(formatAuthApiError(e, '修改密码失败，请稍后重试'));
    } finally {
      setLoading(false);
    }
  };

  return {
    phone,
    smsCode,
    password,
    confirmPassword,
    loading,
    sendingCode,
    cooldown,
    error,
    passwordMismatch,
    canSendCode: !sendingCode && cooldown === 0 && isPhoneValid(phone),
    canSubmit:
      !loading &&
      isPhoneValid(phone) &&
      isSmsCodeValid(smsCode) &&
      isRegisterPasswordValid(password) &&
      password === confirmPassword,
    setPhone: (v: string) => {
      setPhone(sanitizePhoneInput(v));
      setError('');
    },
    setSmsCode: (v: string) => {
      setSmsCode(sanitizeSmsCodeInput(v));
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
    handleSendCode,
    handleSubmit,
  };
}
