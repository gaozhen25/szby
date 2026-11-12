/**
 * 平台分流入口（供 TypeScript 解析）：
 * - Web → voice-recorder.web.ts（MediaRecorder）
 * - Android / iOS → voice-recorder.native.ts（expo-audio）
 *
 * Metro 会优先解析 .web / .native；本文件作为类型与默认回退。
 */
export type { VoiceRecorderResult } from './voice-recorder.web';
export {
  isVoiceRecordingSupported,
  startVoiceRecording,
  cancelVoiceRecording,
  stopVoiceRecording,
} from './voice-recorder.web';
