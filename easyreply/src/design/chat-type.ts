/**
 * 聊天相关字样（会话列表、聊天室），与 src/ui/web/theme.ts 中 webColor / webType / webFontSize 对齐。
 * 原生端引用此文件，避免直接依赖 ui/web（含 antd）。
 */
export const ChatType = {
  color: {
    nameLabel: '#2C2F35',
    subLabel: '#90959D',
    timestamp: '#90959D',
    placeholder: '#8F9193',
    text: '#333333',
    textDetail: '#939BA4',
    onPrimary: '#FFFFFF',
    hint: '#BDC7D2',
    /** 己方聊天气泡底，对齐 webColor.primary */
    bubbleMine: '#5AB2AC',
    /** 对方聊天气泡底，对齐 webColor.peerBubble */
    bubblePeer: '#EBECED',
    /** 聊天消息区背景，对齐 webPageBg.chatRoom */
    chatBg: '#FCFCFC',
    /** 聊天顶栏/输入栏底，对齐 webPageBg.chatHeader */
    chatChrome: '#FCFCFC',
  },
  radius: {
    /** 文本/语音/文件气泡圆角，对齐 Web borderRadius: 10 */
    bubble: 10,
    /** 图片/视频气泡圆角 */
    media: 10,
  },
  size: {
    nameLabel: 14,
    subLabel: 11,
    timestamp: 10,
    bubble: 14,
    chatNavTitle: 16,
    paneTitle: 18,
    pageSubtitle: 12,
    hint: 12,
    previewEmoji: 14,
    bubbleEmoji: 22,
    pureEmoji: 25,
  },
  weight: {
    regular: '400' as const,
    medium: '500' as const,
    semibold: '600' as const,
  },
  lineHeight: {
    nameLabel: 20,
    subLabel: 16,
    timestamp: 14,
    bubble: 20,
    chatNavTitle: 24,
    paneTitle: 24,
    pageSubtitle: 18,
  },
} as const;
