import { useEffect, useState } from 'react';
import { Modal } from 'antd';
import { CloseOutlined } from '@/ui/web/antd-icons';
import { usePathname } from 'expo-router';
import {
  closeProfileModal,
  closeResetPasswordModal,
  subscribeProfileModal,
  type ProfileModalView,
} from '@/lib/profile-modal-bus';
import { ResetPasswordForm } from '@/ui/web/pages/ResetPasswordPage';
import { webModalCloseStyle, webType } from '@/ui/web/theme';

const MODAL_WIDTH = 480;

export function WebProfileHost() {
  const pathname = usePathname() ?? '';
  const [view, setView] = useState<ProfileModalView | null>(null);

  useEffect(() => subscribeProfileModal(setView), []);

  useEffect(() => {
    if (pathname.includes('/login') || pathname.includes('/register')) {
      closeProfileModal();
    }
  }, [pathname]);

  const resetOpen = view === 'reset-password';

  return (
    <Modal
      open={resetOpen}
      title="修改密码"
      footer={null}
      width={MODAL_WIDTH}
      centered
      maskClosable={false}
      closeIcon={<CloseOutlined />}
      onCancel={() => closeResetPasswordModal()}
      styles={{ title: webType.modalTitle, close: webModalCloseStyle }}
      zIndex={2000}
      destroyOnHidden
    >
      <ResetPasswordForm />
    </Modal>
  );
}
