import { isLoggedIn } from '@/core/auth';
import { isImWsUrlConfigured, setImWsUrl } from './config';
import { getChatService, resetChatService } from './chat-service';
import { resetIMConnection } from './connection';
import { imLog, imWarn } from './utils';
let _initialized = false;
export function initIM(): void { if (_initialized) return; _initialized = true; getChatService().init(); if (isImWsUrlConfigured()) imLog('初始化', 'IM 已初始化，WebSocket 地址已配置'); else imLog('初始化', 'IM 已初始化，等待配置 WebSocket 地址后再连接'); }
export async function startIM(options?: { wsUrl?: string }): Promise<void> { initIM(); if (!isLoggedIn()) { imWarn('初始化', '跳过连接：当前未登录'); return; } const chat = getChatService(); if (options?.wsUrl) setImWsUrl(options.wsUrl); if (!chat.isWsConfigured()) { imWarn('初始化', '跳过连接：WebSocket 地址未配置'); return; } imLog('初始化', '登录态有效，开始建立 IM 长连接'); await chat.start(); }
export function stopIM(): void { imLog('初始化', '退出登录：主动断开 IM 连接并重置单例'); getChatService().stop(); resetChatService(); resetIMConnection(); }
export default { initIM, startIM, stopIM };
