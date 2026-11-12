# Web UI（Ant Design）

本目录 **只给 Web 用**，页面与组件一律使用 `antd` / `@ant-design/icons`。

业务页、聊天组件等通过 `@/ui/antd-icons` 取图标：Web 解析为 `@ant-design/icons`，iOS/Android 用同名组件（Ant Design 图标字体）。应用启动图标（`assets/images/icon-qinghui.png`）不替换。

约束：

- 不要 `import 'react-native'` 或 RN 组件（`View` / `Text` / `Pressable` 等）
- 不要被 iOS / Android 入口引用；路由通过 `*.web.tsx` 接入
- 业务与交互放在 `src/features/` 和 `src/chatMessage/`，这里只做排版
- 色值、字号、页面背景、标题字样集中在 `theme.ts` 的 `webColor` / `webFontSize` / `webPageBg` / `webType`，页面不要写死 hex 或 px

原生端后续使用 Ant Design Mobile RN，见 `src/ui/mobile/`。
