// ============================================================
// 修改密码 — 手机号 + 短信验证码重置
// ============================================================
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { router } from 'expo-router';

import { CustomNavBar } from '@/components/UI/CustomNavBar';
import { ScreenCanvas } from '@/components/UI/ScreenCanvas';
import { PasswordInput } from '@/components/auth/PasswordInput';
import { useTheme } from '@/design/theme-context';
import { Tokens } from '@/design/tokens';
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

export default function ResetPasswordScreen() {
  const theme = useTheme();
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
    confirmPassword.length > 0
    && password.length > 0
    && password !== confirmPassword;

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
        {
          text: '知道了',
          onPress: () => router.back(),
        },
      ]);
    } catch (e) {
      setError(formatAuthApiError(e, '修改密码失败，请稍后重试'));
    } finally {
      setLoading(false);
    }
  };

  const canSendCode = !sendingCode && cooldown === 0 && isPhoneValid(phone);
  const canSubmit =
    !loading
    && isPhoneValid(phone)
    && isSmsCodeValid(smsCode)
    && isRegisterPasswordValid(password)
    && password === confirmPassword;

  return (
    <ScreenCanvas safeAreaTop={false}>
      <StatusBar style="dark" />
      <CustomNavBar title="修改密码" onBack={() => router.back()} />

      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <ScrollView
          contentContainerStyle={styles.content}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
          <Text style={[styles.hint, { color: theme.textSubtle }]}>
            通过绑定手机号收取验证码后设置新密码
          </Text>

          {error ? (
            <View style={[styles.errorBox, { backgroundColor: theme.dangerSoft, borderColor: theme.danger + '40' }]}>
              <Text style={[styles.errorText, { color: theme.danger }]}>{error}</Text>
            </View>
          ) : null}

          <View style={styles.field}>
            <Text style={[styles.label, { color: theme.text }]}>手机号</Text>
            <TextInput
              style={[
                styles.input,
                {
                  color: theme.text,
                  backgroundColor: theme.surface2,
                  borderColor: theme.border,
                },
              ]}
              placeholder="请输入绑定手机号"
              placeholderTextColor={theme.placeholder}
              value={phone}
              onChangeText={(t) => { setPhone(sanitizePhoneInput(t)); setError(''); }}
              keyboardType="phone-pad"
              maxLength={11}
              editable={!boundPhone}
            />
            {boundPhone ? (
              <Text style={[styles.fieldHint, { color: theme.textSubtle }]}>
                已自动填入当前账号绑定手机号
              </Text>
            ) : null}
          </View>

          <View style={styles.field}>
            <Text style={[styles.label, { color: theme.text }]}>验证码</Text>
            <View style={styles.codeRow}>
              <TextInput
                style={[
                  styles.input,
                  styles.codeInput,
                  {
                    color: theme.text,
                    backgroundColor: theme.surface2,
                    borderColor: theme.border,
                  },
                ]}
                placeholder="6 位验证码"
                placeholderTextColor={theme.placeholder}
                value={smsCode}
                onChangeText={(t) => { setSmsCode(sanitizeSmsCodeInput(t)); setError(''); }}
                keyboardType="number-pad"
                maxLength={6}
              />
              <TouchableOpacity
                style={[
                  styles.codeBtn,
                  { backgroundColor: canSendCode ? theme.primary : theme.divider },
                ]}
                onPress={handleSendCode}
                disabled={!canSendCode}
                activeOpacity={0.8}
              >
                {sendingCode ? (
                  <ActivityIndicator size="small" color="#fff" />
                ) : (
                  <Text style={styles.codeBtnText}>
                    {cooldown > 0 ? `${cooldown}s` : '获取验证码'}
                  </Text>
                )}
              </TouchableOpacity>
            </View>
          </View>

          <View style={styles.field}>
            <Text style={[styles.label, { color: theme.text }]}>新密码</Text>
            <PasswordInput
              placeholder="6~20 位"
              placeholderTextColor={theme.placeholder}
              value={password}
              onChangeText={(t) => { setPassword(sanitizePasswordInput(t)); setError(''); }}
              style={[
                styles.input,
                {
                  color: theme.text,
                  backgroundColor: theme.surface2,
                  borderColor: theme.border,
                },
              ]}
            />
          </View>

          <View style={styles.field}>
            <Text style={[styles.label, { color: theme.text }]}>确认新密码</Text>
            <PasswordInput
              placeholder="请再次输入新密码"
              placeholderTextColor={theme.placeholder}
              value={confirmPassword}
              onChangeText={(t) => {
                setConfirmPassword(sanitizePasswordInput(t));
                setError('');
              }}
              style={[
                styles.input,
                {
                  color: theme.text,
                  backgroundColor: theme.surface2,
                  borderColor: theme.border,
                },
              ]}
              onSubmitEditing={handleSubmit}
            />
            {passwordMismatch ? (
              <Text style={[styles.fieldError, { color: theme.danger }]}>两次输入的密码不一致</Text>
            ) : null}
          </View>

          <Pressable
            style={[
              styles.submitBtn,
              { backgroundColor: canSubmit ? theme.primary : theme.divider },
            ]}
            onPress={handleSubmit}
            disabled={!canSubmit}
          >
            {loading ? (
              <ActivityIndicator size="small" color="#fff" />
            ) : (
              <Text style={styles.submitText}>确认修改</Text>
            )}
          </Pressable>
        </ScrollView>
      </KeyboardAvoidingView>
    </ScreenCanvas>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  content: {
    paddingHorizontal: Tokens.spacing[4],
    paddingTop: Tokens.spacing[4],
    paddingBottom: Tokens.spacing[8],
  },
  hint: {
    fontSize: 13,
    lineHeight: 18,
    marginBottom: Tokens.spacing[4],
  },
  errorBox: {
    borderRadius: Tokens.radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    paddingVertical: 10,
    paddingHorizontal: 14,
    marginBottom: Tokens.spacing[4],
  },
  errorText: {
    fontSize: 13,
    lineHeight: 18,
  },
  field: {
    marginBottom: Tokens.spacing[4],
  },
  label: {
    fontSize: 14,
    fontWeight: '500',
    marginBottom: 8,
  },
  fieldHint: {
    fontSize: 12,
    marginTop: 6,
  },
  fieldError: {
    fontSize: 12,
    marginTop: 6,
  },
  input: {
    height: 48,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: Tokens.radius.md,
    paddingHorizontal: 14,
    fontSize: 16,
  },
  codeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  codeInput: {
    flex: 1,
  },
  codeBtn: {
    height: 48,
    minWidth: 112,
    paddingHorizontal: 12,
    borderRadius: Tokens.radius.md,
    alignItems: 'center',
    justifyContent: 'center',
  },
  codeBtnText: {
    fontSize: 14,
    fontWeight: '600',
    color: '#fff',
  },
  submitBtn: {
    height: 50,
    borderRadius: Tokens.radius.md,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: Tokens.spacing[2],
  },
  submitText: {
    fontSize: 17,
    fontWeight: '600',
    color: '#fff',
  },
});
