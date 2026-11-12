/** TypeScript / 默认入口；Metro 在 native/web 上会优先解析对应平台文件 */
export { logStore } from './log-store.native';
export type { LogStore, LogStoreFileInfo } from './log-store.types';
export { logFileName, parseLogFileName } from './log-store.types';
