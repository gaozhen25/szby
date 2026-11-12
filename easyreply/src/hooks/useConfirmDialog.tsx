import { useCallback } from 'react';

import { appAlert } from '@/lib/app-alert';

export type ConfirmOptions = {
  title: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  destructive?: boolean;
  onConfirm: () => void | Promise<void>;
};

/**
 * 跨端确认弹窗（内部走 appAlert，Web 由根布局 AppAlertHost 渲染）。
 * 保留 `ConfirmDialogHost` 空壳以兼容现有调用方。
 */
export function useConfirmDialog() {
  const confirm = useCallback((opts: ConfirmOptions) => {
    appAlert(opts.title, opts.message, [
      { text: opts.cancelText ?? '取消', style: 'cancel' },
      {
        text: opts.confirmText ?? '确认',
        style: opts.destructive ? 'destructive' : 'default',
        onPress: () => {
          void Promise.resolve(opts.onConfirm());
        },
      },
    ]);
  }, []);

  function ConfirmDialogHost() {
    return null;
  }

  return { confirm, ConfirmDialogHost };
}
