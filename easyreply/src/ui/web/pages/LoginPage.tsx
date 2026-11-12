/**
 * THESIS: 全屏水波上的门厅；拒绝双栏品牌轨与居中灰卡。
 * OWN-WORLD: 薄荷洗底、连续水面起伏与光斑、点击水窝；玻璃卡承品牌与表单，10px 控件圆角、主色按钮。
 * STORY: 账号密码进工作台；没有账号去注册。
 * FIRST VIEWPORT: 居中卡：标志、产品名、客服工作台、账号密码、登录。
 * FORM: 波纹舞台上的单卡登录。
 */
import { Alert, Button, Form, Input, Typography } from 'antd';
import { router } from 'expo-router';
import { useLogin } from '@/features/auth/useLogin';
import { AuthSplit } from '@/ui/web/pages/AuthSplit';

export default function LoginPage() {
  const login = useLogin();

  return (
    <AuthSplit eyebrow="客服工作台">
      <div className="qh-auth-form-title">账号密码登录</div>

      {login.error ? (
        <Alert type="error" title={login.error} showIcon style={{ marginBottom: 16 }} />
      ) : null}

      <Form layout="vertical" onFinish={() => void login.handleLogin()} requiredMark={false}>
        <Form.Item label="账号">
          <Input
            size="large"
            placeholder="3~20 位，可为手机号"
            value={login.account}
            onChange={(e) => login.setAccount(e.target.value)}
            maxLength={20}
            autoComplete="username"
            autoFocus
          />
        </Form.Item>
        <Form.Item label="密码">
          <Input.Password
            size="large"
            placeholder="6~20 位"
            value={login.password}
            onChange={(e) => login.setPassword(e.target.value)}
            maxLength={20}
            autoComplete="current-password"
            onPressEnter={() => void login.handleLogin()}
          />
        </Form.Item>
        <Button
          type="primary"
          htmlType="submit"
          size="large"
          block
          className="qh-auth-submit"
          loading={login.loading}
          disabled={!login.canLogin}
        >
          登录
        </Button>
      </Form>

      <div className="qh-auth-switch">
        <span>没有账号？</span>
        <button type="button" className="qh-auth-link" onClick={() => router.push('/register')}>
          去注册
        </button>
      </div>
      {/* <Typography.Text className="qh-auth-agreement">
        登录即表示同意《用户协议》和《隐私政策》
      </Typography.Text> */}
    </AuthSplit>
  );
}
