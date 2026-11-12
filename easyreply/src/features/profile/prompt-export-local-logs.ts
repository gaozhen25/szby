import { appAlert } from '@/lib/app-alert';
import { exportLocalLogs, LOG_EXPORT_RANGE_LABEL, type LogExportRange } from '@/core/logging';

function runExport(range: LogExportRange): void {
  void exportLocalLogs(range).then((result) => {
    appAlert(result.ok ? '导出日志' : '导出失败', result.message);
  });
}

/** 先选时间范围，再导出诊断日志 */
export function promptExportLocalLogs(): void {
  appAlert('导出诊断日志', '请选择要导出的时间范围', [
    { text: LOG_EXPORT_RANGE_LABEL['3h'], style: 'default', onPress: () => runExport('3h') },
    { text: LOG_EXPORT_RANGE_LABEL.today, style: 'default', onPress: () => runExport('today') },
    { text: LOG_EXPORT_RANGE_LABEL.all, style: 'default', onPress: () => runExport('all') },
    { text: '取消', style: 'cancel' },
  ]);
}
