import { Alert, Button, Flex, Form, Input } from 'antd';
import { router } from 'expo-router';
import { useRegister } from '@/features/auth/useRegister';
import { AuthSplit } from '@/ui/web/pages/AuthSplit';

export default function RegisterPage() {
  const form = useRegister();

  return (
    <AuthSplit eyebrow="客服工作台">
      <div className="qh-auth-form-title">创建账号</div>

      {form.error ? (
        <Alert type="error" title={form.error} showIcon style={{ marginBottom: 16 }} />
      ) : null}

      <Form layout="vertical" onFinish={() => void form.handleRegister()} requiredMark={false}>
        <Form.Item label="账号">
          <Input
            size="large"
            placeholder="3~20 位，可为手机号"
            value={form.account}
            onChange={(e) => form.setAccount(e.target.value)}
            maxLength={20}
            autoComplete="username"
            autoFocus
          />
        </Form.Item>
        <Form.Item label="密码">
          <Input.Password
            size="large"
            placeholder="6~20 位"
            value={form.password}
            onChange={(e) => form.setPassword(e.target.value)}
            maxLength={20}
            autoComplete="new-password"
          />
        </Form.Item>
        <Form.Item
          label="确认密码"
          validateStatus={form.passwordMismatch ? 'error' : undefined}
          help={form.passwordMismatch ? '两次输入的密码不一致' : undefined}
        >
          <Input.Password
            size="large"
            placeholder="再次输入密码"
            value={form.confirmPassword}
            onChange={(e) => form.setConfirmPassword(e.target.value)}
            maxLength={20}
            autoComplete="new-password"
          />
        </Form.Item>
        <Form.Item label="手机号">
          <Input
            size="large"
            placeholder="11 位手机号"
            value={form.phone}
            onChange={(e) => form.setPhone(e.target.value)}
            maxLength={11}
            autoComplete="tel"
          />
        </Form.Item>
        <Form.Item label="验证码">
          <Flex gap={8}>
            <Input
              size="large"
              placeholder="短信验证码"
              value={form.smsCode}
              onChange={(e) => form.setSmsCode(e.target.value)}
              maxLength={6}
              autoComplete="one-time-code"
            />
            <Button
              size="large"
              disabled={!form.canSendCode}
              loading={form.sendingCode}
              onClick={() => void form.handleSendCode()}
            >
              {form.cooldown > 0 ? `${form.cooldown}s` : '获取验证码'}
            </Button>
          </Flex>
        </Form.Item>
        <Button
          type="primary"
          htmlType="submit"
          size="large"
          block
          className="qh-auth-submit"
          loading={form.loading}
        >
          注册
        </Button>
      </Form>

      <div className="qh-auth-switch">
        <span>已有账号？</span>
        <button type="button" className="qh-auth-link" onClick={() => router.replace('/login')}>
          去登录
        </button>
      </div>
    </AuthSplit>
  );
}
