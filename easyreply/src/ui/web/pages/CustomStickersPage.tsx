import { useCallback, useEffect, useState } from 'react';
import { router } from 'expo-router';
import { AppShell } from '@/ui/web/AppShell';
import { WebCustomStickersModal } from '@/ui/web/chat/WebCustomStickersModal';

/** 路由入口：以弹窗展示，关闭后返回上一页 */
export default function CustomStickersPage() {
  const [open, setOpen] = useState(true);

  const handleClose = useCallback(() => {
    setOpen(false);
    if (router.canGoBack()) router.back();
    else router.replace('/(tabs)/chat');
  }, []);

  useEffect(() => {
    setOpen(true);
  }, []);

  return (
    <AppShell>
      <WebCustomStickersModal open={open} onClose={handleClose} />
    </AppShell>
  );
}
