/**
 * 平台分流入口（供 TypeScript 解析）：
 * - Web → voice-player.web.ts
 * - Android / iOS → voice-player.native.ts
 */
export { playVoiceUrl, stopVoicePlayback } from './voice-player.web';
