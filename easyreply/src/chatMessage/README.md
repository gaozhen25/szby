# ChatMessage 模块说明

聊天页重构后的业务实现统一收口在 `src/chatMessage/`。

## 目录职责

- `components/`：聊天 UI 组件（列表、气泡、输入区、菜单、弹窗等）
- `message/`：消息域工具（展示模型、本地缓存、表情/图片工具）
- `room/`：聊天房运行时（session、ownership、gateway、send、gate）
- `index.ts`：模块统一出口（供上层页面直接导入）

## 使用约定

1. 新增聊天功能时，优先从 `@/chatMessage` 或其子目录导入；
2. `src/hooks/useChat*.ts`、`src/lib/chat-*.ts`、`src/app/components/chat/*.ts` 仅作为兼容层（re-export），不要再放业务实现；
3. 路由页面入口保持在 `src/app/chat/[id].tsx`（expo-router 约束），但业务逻辑应继续下沉到 `chatMessage`。

## 兼容层说明

为避免一次性全仓改动，旧路径已保留为 shim（转发导出）。后续逐步清理调用方时，可按需删除这些 shim。

### 当前 shim 范围

- `src/app/components/chat/*.ts`
- `src/hooks/useChatGatewayEvents.ts`
- `src/hooks/useChatOwnership.ts`
- `src/hooks/useChatRoomMessages.ts`
- `src/hooks/useChatRoomSession.ts`
- `src/hooks/useChatSend.ts`
- `src/hooks/useChatTaskActions.ts`
- `src/hooks/useKeyboardOffset.ts`
- `src/lib/active-chat-session.ts`
- `src/lib/chat-emoji-draft.ts`
- `src/lib/chat-image-size.ts`
- `src/lib/chat-input-gate.ts`
- `src/lib/chat-message-model.ts`
- `src/lib/chat-messages-cache.ts`
- `src/lib/chat-room-handle.ts`

### 建议删除顺序

1. 先保证业务文件全部直连 `@/chatMessage`；
2. 再删除 `app/components/chat/*.ts`；
3. 再删除 `hooks/useChat*.ts` 兼容层；
4. 最后删除 `lib/chat-*.ts` 兼容层。
