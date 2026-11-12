// ============================================================
// 轻回 App - 登录页（账号 + 密码）
// ============================================================
import { useEffect, useState } from 'react';
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
} from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { router } from 'expo-router';
import { login, formatAuthApiError } from '@/api/auth';
import { completeAuthFlow } from '@/core/auth-flow';
import { loadLoginCredentials } from '@/core/auth-persist';
import { ScreenCanvas } from '@/components/UI/ScreenCanvas';
import { PasswordInput } from '@/components/auth/PasswordInput';
import {
  sanitizeAccountInput,
  sanitizePasswordInput,
  validateAccount,
  validatePassword,
  isAccountValid,
  isPasswordValid,
} from '@/components/auth/credentials';
import { APP_NAME } from '@/lib/api-host';

export default function LoginScreen() {
  const [account, setAccount] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // 退出登录后：自动填充上次登录的账号密码
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

  const canLogin = !loading && isAccountValid(account) && isPasswordValid(password);

  return (
    <ScreenCanvas>
      <KeyboardAvoidingView
        style={styles.container}
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      >
        <StatusBar style="dark" />

        <View style={styles.inner}>
          <View style={styles.brand}>
            <Image
              source={require('../../assets/images/icon-qinghui.png')}
              style={styles.logoImage}
              accessibilityLabel={APP_NAME}
              resizeMode="contain"
            />
            <Text style={styles.appName}>{APP_NAME}</Text>
            <Text style={styles.subtitle}>账号密码登录</Text>
          </View>

          {error ? (
            <View style={styles.errorBox}>
              <Text style={styles.errorText}>{error}</Text>
            </View>
          ) : null}

          <View style={styles.inputGroup}>
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

          <View style={styles.inputGroup}>
            <Text style={styles.label}>密码</Text>
            <PasswordInput
              placeholder="6~20 位"
              placeholderTextColor="#C0C0C0"
              value={password}
              onChangeText={(t) => { setPassword(sanitizePasswordInput(t)); setError(''); }}
              returnKeyType="done"
              onSubmitEditing={handleLogin}
            />
          </View>

          <TouchableOpacity
            style={[styles.primaryBtn, !canLogin && styles.primaryBtnDisabled]}
            onPress={handleLogin}
            disabled={!canLogin}
            activeOpacity={0.8}
          >
            {loading ? (
              <ActivityIndicator size="small" color="#fff" />
            ) : (
              <Text style={styles.primaryBtnText}>登录</Text>
            )}
          </TouchableOpacity>

          <Pressable style={styles.linkRow} onPress={() => router.push('/register')}>
            <Text style={styles.linkText}>没有账号？去注册</Text>
          </Pressable>

          {/* <Text style={styles.agreement}>
            登录即表示同意《用户协议》和《隐私政策》
          </Text> */}
        </View>
      </KeyboardAvoidingView>
    </ScreenCanvas>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  inner: { flex: 1, paddingHorizontal: 32, justifyContent: 'center' },
  brand: { alignItems: 'center', marginBottom: 48 },
  logoImage: { width: 88, height: 88, marginBottom: 12 },
  appName: {
    fontSize: 28,
    fontWeight: '700',
    color: '#1A1A1A',
    letterSpacing: 2,
    marginBottom: 8,
  },
  subtitle: { fontSize: 15, color: '#999' },
  errorBox: {
    backgroundColor: '#FFF2F0',
    borderRadius: 8,
    paddingVertical: 10,
    paddingHorizontal: 14,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: '#FFCCC7',
  },
  errorText: { color: '#FF4D4F', fontSize: 13, lineHeight: 18 },
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
  primaryBtn: {
    height: 50,
    borderRadius: 8,
    backgroundColor: '#4A90D9',
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 12,
  },
  primaryBtnDisabled: { backgroundColor: '#B0C4DE' },
  primaryBtnText: { fontSize: 17, fontWeight: '600', color: '#fff' },
  linkRow: { alignItems: 'center', marginTop: 20 },
  linkText: { fontSize: 14, color: '#4A90D9', fontWeight: '500' },
  agreement: {
    textAlign: 'center',
    marginTop: 24,
    fontSize: 12,
    color: '#B0B0B0',
    lineHeight: 18,
  },
});
