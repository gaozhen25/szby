import { Alert, Button, Flex, Form, Input } from 'antd';
import { useResetPassword } from '@/features/auth/useResetPassword';
import { closeResetPasswordModal } from '@/lib/profile-modal-bus';

export function ResetPasswordForm({ onSuccess }: { onSuccess?: () => void }) {
  const form = useResetPassword({
    onSuccess: onSuccess ?? closeResetPasswordModal,
  });

  return (
    <Form layout="vertical" onFinish={() => void form.handleSubmit()}>
      {form.error ? <Alert type="error" title={form.error} showIcon style={{ marginBottom: 16 }} /> : null}
      <Form.Item label="手机号">
        <Input value={form.phone} onChange={(e) => form.setPhone(e.target.value)} maxLength={11} />
      </Form.Item>
      <Form.Item label="验证码">
        <Flex gap={8}>
          <Input value={form.smsCode} onChange={(e) => form.setSmsCode(e.target.value)} maxLength={6} />
          <Button disabled={!form.canSendCode} loading={form.sendingCode} onClick={() => void form.handleSendCode()}>
            {form.cooldown > 0 ? `${form.cooldown}s` : '获取验证码'}
          </Button>
        </Flex>
      </Form.Item>
      <Form.Item label="新密码">
        <Input.Password value={form.password} onChange={(e) => form.setPassword(e.target.value)} maxLength={20} />
      </Form.Item>
      <Form.Item
        label="确认密码"
        validateStatus={form.passwordMismatch ? 'error' : undefined}
        help={form.passwordMismatch ? '两次输入的密码不一致' : undefined}
      >
        <Input.Password
          value={form.confirmPassword}
          onChange={(e) => form.setConfirmPassword(e.target.value)}
          maxLength={20}
        />
      </Form.Item>
      <Button type="primary" htmlType="submit" block loading={form.loading} disabled={!form.canSubmit}>
        提交
      </Button>
    </Form>
  );
}

export default ResetPasswordForm;
