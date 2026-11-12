import { useEffect } from 'react';
import { Redirect } from 'expo-router';
import { useIsDesktopWeb } from '@/lib/web-desktop';
import { openProfileModal } from '@/lib/profile-modal-bus';
import NativeProfile from './profile.tsx';

/** 桌面 Web：深链进入「我的」时落到工作台并以弹窗打开；窄屏使用手机端 Tab */
export default function ProfileTabWeb() {
  const isDesktop = useIsDesktopWeb();

  useEffect(() => {
    if (isDesktop) openProfileModal('profile');
  }, [isDesktop]);

  if (!isDesktop) {
    return <NativeProfile />;
  }

  return <Redirect href="/(tabs)/chat" />;
}
