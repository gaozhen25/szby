import { useEffect } from 'react';
import { Redirect } from 'expo-router';
import { useIsDesktopWeb } from '@/lib/web-desktop';
import { openProfileModal } from '@/lib/profile-modal-bus';
import NativeResetPassword from './reset-password.tsx';

/** 桌面 Web：深链进入修改密码时落到工作台并以弹窗打开；窄屏使用手机端页面 */
export default function ResetPasswordWebRedirect() {
  const isDesktop = useIsDesktopWeb();

  useEffect(() => {
    if (isDesktop) openProfileModal('reset-password');
  }, [isDesktop]);

  if (!isDesktop) {
    return <NativeResetPassword />;
  }

  return <Redirect href="/(tabs)/chat" />;
}
