// ============================================================
// 轻回 App - 注册页（账号 + 密码 + 手机号验证码）
// 上下固定，中间表单可滚动；提交时自动滚到首个未填/无效项
// ============================================================
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Image,
  Pressable,
  ScrollView,
  type LayoutChangeEvent,
} from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { router } from 'expo-router';
import { login, registerAccount, sendAuthCode, formatAuthApiError } from '@/api/auth';
import { completeAuthFlow } from '@/core/auth-flow';
import { ApiError } from '@/lib/http';
import { APP_NAME } from '@/lib/api-host';
import { ScreenCanvas } from '@/components/UI/ScreenCanvas';
import { PasswordInput } from '@/components/auth/PasswordInput';
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

type FieldKey = 'account' | 'password' | 'confirmPassword' | 'phone' | 'smsCode';

export default function RegisterScreen() {
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
  const scrollRef = useRef<ScrollView>(null);
  const fieldYRef = useRef<Partial<Record<FieldKey, number>>>({});

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

  const recordFieldY = useCallback((key: FieldKey) => (e: LayoutChangeEvent) => {
    fieldYRef.current[key] = e.nativeEvent.layout.y;
  }, []);

  const scrollToField = useCallback((key: FieldKey) => {
    const y = fieldYRef.current[key];
    if (y == null) return;
    scrollRef.current?.scrollTo({ y: Math.max(0, y - 12), animated: true });
  }, []);

  const failField = useCallback((key: FieldKey, message: string) => {
    setError(message);
    scrollToField(key);
  }, [scrollToField]);

  const passwordMismatch =
    confirmPassword.length > 0
    && password.length > 0
    && password !== confirmPassword;

  const handleSendCode = async () => {
    setError('');
    const phoneErr = validatePhone(phone);
    if (phoneErr) {
      failField('phone', phoneErr);
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
      failField('account', accountErr);
      return;
    }
    const pwdErr = validateRegisterPassword(password);
    if (pwdErr) {
      failField('password', pwdErr);
      return;
    }
    if (password !== confirmPassword) {
      failField('confirmPassword', '两次输入的密码不一致');
      return;
    }
    const phoneErr = validatePhone(phone);
    if (phoneErr) {
      failField('phone', phoneErr);
      return;
    }
    const codeErr = validateSmsCode(smsCode);
    if (codeErr) {
      failField('smsCode', codeErr);
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
      // 注册已成功，账号待管理员启用时自动登录会返回 account_disabled
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

  const canSendCode = !sendingCode && cooldown === 0 && isPhoneValid(phone);

  return (
    <ScreenCanvas>
      <KeyboardAvoidingView
        style={styles.container}
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      >
        <StatusBar style="dark" />

        {/* 上方固定：品牌 + 错误提示 */}
        <View style={styles.header}>
          <Image
            source={require('../../assets/images/icon-qinghui.png')}
            style={styles.logoImage}
            accessibilityLabel={APP_NAME}
            resizeMode="contain"
          />
          <Text style={styles.subtitle}>创建账号</Text>
          {error ? (
            <View style={styles.errorBox}>
              <Text style={styles.errorText}>{error}</Text>
            </View>
          ) : null}
        </View>

        {/* 中间滚动：表单 */}
        <ScrollView
          ref={scrollRef}
          style={styles.scroll}
          contentContainerStyle={styles.scrollContent}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
          <View style={styles.inputGroup} onLayout={recordFieldY('account')}>
            <Text style={styles.label}>账号</Text>
            <TextInput
              style={styles.input}
              placeholder="3~20 位，可为手机号"
              placeholderTextColor="#C0C0C0"
              value={account}
              onChangeText={(t) => { setAccount(sanitizeAccountInput(t)); setError(''); }}
              autoCapitalize="none"
              autoCorrect={false}
              maxLength={20}
              returnKeyType="next"
            />
          </View>

          <View style={styles.inputGroup} onLayout={recordFieldY('password')}>
            <Text style={styles.label}>密码</Text>
            <PasswordInput
              placeholder="6~20 位"
              placeholderTextColor="#C0C0C0"
              value={password}
              onChangeText={(t) => { setPassword(sanitizePasswordInput(t)); setError(''); }}
              returnKeyType="next"
            />
          </View>

          <View style={styles.inputGroup} onLayout={recordFieldY('confirmPassword')}>
            <Text style={styles.label}>确认密码</Text>
            <PasswordInput
              placeholder="请再次输入密码"
              placeholderTextColor="#C0C0C0"
              value={confirmPassword}
              onChangeText={(t) => {
                setConfirmPassword(sanitizePasswordInput(t));
                setError('');
              }}
              returnKeyType="next"
            />
            {passwordMismatch ? (
              <Text style={styles.fieldError}>两次输入的密码不一致</Text>
            ) : null}
          </View>

          <View style={styles.inputGroup} onLayout={recordFieldY('phone')}>
            <Text style={styles.label}>手机号</Text>
            <TextInput
              style={styles.input}
              placeholder="请输入手机号"
              placeholderTextColor="#C0C0C0"
              value={phone}
              onChangeText={(t) => { setPhone(sanitizePhoneInput(t)); setError(''); }}
              keyboardType="phone-pad"
              maxLength={11}
              returnKeyType="next"
            />
          </View>

          <View style={styles.inputGroup} onLayout={recordFieldY('smsCode')}>
            <Text style={styles.label}>验证码</Text>
            <View style={styles.codeRow}>
              <TextInput
                style={[styles.input, styles.codeInput]}
                placeholder="6 位验证码"
                placeholderTextColor="#C0C0C0"
                value={smsCode}
                onChangeText={(t) => { setSmsCode(sanitizeSmsCodeInput(t)); setError(''); }}
                keyboardType="number-pad"
                maxLength={6}
                returnKeyType="done"
                onSubmitEditing={handleRegister}
              />
              <TouchableOpacity
                style={[styles.codeBtn, !canSendCode && styles.codeBtnDisabled]}
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
        </ScrollView>

        {/* 下方固定：注册 + 去登录 */}
        <View style={styles.footer}>
          <TouchableOpacity
            style={[styles.primaryBtn, loading && styles.primaryBtnDisabled]}
            onPress={handleRegister}
            disabled={loading}
            activeOpacity={0.8}
          >
            {loading ? (
              <ActivityIndicator size="small" color="#fff" />
            ) : (
              <Text style={styles.primaryBtnText}>注册</Text>
            )}
          </TouchableOpacity>

          <Pressable style={styles.linkRow} onPress={() => router.replace('/login')}>
            <Text style={styles.linkText}>已有账号？去登录</Text>
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </ScreenCanvas>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  header: {
    alignItems: 'center',
    paddingTop: 12,
    paddingBottom: 4,
    paddingHorizontal: 32,
  },
  logoImage: { width: 56, height: 56, marginBottom: 6 },
  subtitle: { fontSize: 13, color: '#999', marginBottom: 0 },
  scroll: { flex: 1 },
  scrollContent: {
    paddingHorizontal: 32,
    paddingTop: 12,
    paddingBottom: 16,
  },
  footer: {
    paddingHorizontal: 32,
    paddingTop: 8,
    paddingBottom: Platform.OS === 'ios' ? 28 : 20,
  },
  errorBox: {
    alignSelf: 'stretch',
    backgroundColor: '#FFF2F0',
    borderRadius: 8,
    paddingVertical: 8,
    paddingHorizontal: 12,
    marginTop: 8,
    borderWidth: 1,
    borderColor: '#FFCCC7',
  },
  errorText: { color: '#FF4D4F', fontSize: 13, lineHeight: 18 },
  fieldError: { color: '#FF4D4F', fontSize: 12, lineHeight: 16, marginTop: 6 },
  inputGroup: { marginBottom: 20 },
  label: { fontSize: 14, fontWeight: '500', color: '#333', marginBottom: 8 },
  input: {
    height: 48,
    borderWidth: 1,
    borderColor: '#E0E0E0',
    borderRadius: 8,
    paddingHorizontal: 14,
    fontSize: 16,
    color: '#1A1A1A',
    backgroundColor: '#FAFAFA',
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
    borderRadius: 8,
    backgroundColor: '#4A90D9',
    alignItems: 'center',
    justifyContent: 'center',
  },
  codeBtnDisabled: { backgroundColor: '#B0C4DE' },
  codeBtnText: { fontSize: 14, fontWeight: '600', color: '#fff' },
  primaryBtn: {
    height: 50,
    borderRadius: 8,
    backgroundColor: '#4A90D9',
    alignItems: 'center',
    justifyContent: 'center',
  },
  primaryBtnDisabled: { backgroundColor: '#B0C4DE' },
  primaryBtnText: { fontSize: 17, fontWeight: '600', color: '#fff' },
  linkRow: { alignItems: 'center', marginTop: 16 },
  linkText: { fontSize: 14, color: '#4A90D9', fontWeight: '500' },
});
