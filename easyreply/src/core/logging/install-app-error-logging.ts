import { Platform } from 'react-native';
import { logApp, flushLocalLogs } from './local-logger';

type ErrorUtilsShape = {
  getGlobalHandler?: () => ((error: Error, isFatal?: boolean) => void) | undefined;
  setGlobalHandler?: (handler: (error: Error, isFatal?: boolean) => void) => void;
};

let installed = false;

function toErrorMessage(reason: unknown): string {
  if (reason instanceof Error) {
    return `${reason.name}: ${reason.message}`;
  }
  try {
    return JSON.stringify(reason);
  } catch {
    return String(reason);
  }
}

/** 安装全局未捕获错误监听（可重复调用，仅生效一次） */
export function installAppErrorLogging(): void {
  if (installed) return;
  installed = true;

  // React Native ErrorUtils
  try {
    const errorUtils = (globalThis as { ErrorUtils?: ErrorUtilsShape }).ErrorUtils;
    if (errorUtils?.getGlobalHandler && errorUtils.setGlobalHandler) {
      const prev = errorUtils.getGlobalHandler();
      errorUtils.setGlobalHandler((error, isFatal) => {
        logApp(isFatal ? 'fatal' : 'uncaught', {
          name: error?.name,
          message: error?.message,
          stack: error?.stack,
          isFatal: !!isFatal,
        });
        void flushLocalLogs();
        prev?.(error, isFatal);
      });
    }
  } catch {
    /* ignore */
  }

  // Web
  if (Platform.OS === 'web' && typeof window !== 'undefined') {
    window.addEventListener('error', (event) => {
      logApp('window.onerror', {
        message: event.message,
        filename: event.filename,
        lineno: event.lineno,
        colno: event.colno,
        stack: event.error instanceof Error ? event.error.stack : undefined,
      });
      void flushLocalLogs();
    });
    window.addEventListener('unhandledrejection', (event) => {
      logApp('unhandledrejection', { reason: toErrorMessage(event.reason) });
      void flushLocalLogs();
    });
  }
}

/** 供 ErrorBoundary 显式写入 */
export function logBoundaryError(error: Error): void {
  logApp('ErrorBoundary', {
    name: error.name,
    message: error.message,
    stack: error.stack,
  });
  void flushLocalLogs();
}
