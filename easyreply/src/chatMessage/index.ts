/**
 * 聊天模块统一出口。
 *
 * 说明：
 * - `components/`：聊天 UI 组件
 * - `list/`：列表滚动 / 锚点 / 首屏揭示（视图无关）
 * - `composer/`：输入区面板与录音交互（视图无关）
 * - `message/`：消息模型、缓存、图片/表情工具
 * - `room/`：聊天房运行时（session / ownership / gateway / send / gate / screen）
 *
 * 路由入口仍在 `src/app/chat/[id].tsx`，这里只收口业务实现，方便查阅。
 */
export * from './components';
export * from './message';
export * from './room';
export * from './stickerPack';
export { useChatListController } from './list';
export { useComposerChrome } from './composer';
