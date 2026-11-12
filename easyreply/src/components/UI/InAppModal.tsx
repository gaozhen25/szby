import type { ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { Modal, Platform, StyleSheet, View, type ModalProps } from 'react-native';

import { getAppOverlayHost } from '@/lib/app-overlay-host';

type Props = Pick<ModalProps, 'visible' | 'transparent' | 'animationType' | 'onRequestClose'> & {
  children: ReactNode;
  /** 仅原生：是否透传 statusBarTranslucent */
  statusBarTranslucent?: boolean;
};

/**
 * 应用内弹层：
 * - 原生：RN Modal（全屏）
 * - Web：挂到 WebPhoneShell 内的 overlay host，不超出手机框
 */
export function InAppModal({
  visible,
  transparent = true,
  animationType = 'fade',
  onRequestClose,
  statusBarTranslucent,
  children,
}: Props) {
  if (Platform.OS !== 'web') {
    return (
      <Modal
        visible={!!visible}
        transparent={transparent}
        animationType={animationType}
        onRequestClose={onRequestClose}
        statusBarTranslucent={statusBarTranslucent}
      >
        {children}
      </Modal>
    );
  }

  if (!visible || typeof document === 'undefined') return null;

  const host = getAppOverlayHost() ?? document.body;
  return createPortal(
    <View style={styles.webLayer} pointerEvents="box-none">
      {children}
    </View>,
    host,
  );
}

const styles = StyleSheet.create({
  webLayer: {
    ...StyleSheet.absoluteFillObject,
    zIndex: 100000,
  },
});
