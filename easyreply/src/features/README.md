# Features（公共交互）

跨端共用的业务 hooks / 启动逻辑，**不含 Button / 列表等 UI 组件**。

- Web 用 `src/ui/web` 接这些 hooks
- 手机用 `src/app`（及日后的 `src/ui/mobile`）接同一套 hooks

聊天房接线已在 `src/chatMessage/`（`useChatRoomScreen` 等），本目录补认证、会话列表、根启动等。
