import type { CSSProperties } from 'react';
import type { ThemeConfig } from 'antd';

/**
 * Web 色值。改这里即可全局换色，页面不要再写死 hex。
 *
 * 对齐客户端宏：Color_Text_Base / Color_Text_Detail / Color_Text_remind /
 * Color_Separator / Color_Background_Base / Color_RedColor
 */
export const webColor = {
  /** 标题、表单默认文字 */
  text: '#333333',
  /** 列表主标题（会话 name） */
  nameLabel: '#2C2F35',
  /** 列表副标题（最后一条消息） */
  subLabel: '#90959D',
  /** 正文、表单填写后文字 */
  textDetail: '#939BA4',
  /** 辅助、提示文字 */
  textRemind: '#BDC7D2',
  /** 时间戳 */
  timestamp: '#90959D',
  /** 主色上的文字 */
  onPrimary: '#FFFFFF',
  /** 输入占位 */
  placeholder: '#8F9193',
  /** 分割线、不可点击按钮 */
  separator: '#F0F1F3',
  /** 默认页面背景 */
  bg: '#F5F6F8',
  /** 第一栏（侧栏）背景。桌面皮肤切换见 chrome-theme.ts */
  sidebar: '#E3EBF8',
  /** 第二/三栏背景。桌面皮肤切换见 chrome-theme.ts */
  pane: '#FCFCFC',
  /** 聊天消息区背景（第四栏）。桌面皮肤切换见 chrome-theme.ts */
  chatBg: '#FCFCFC',
  /** 卡片/容器底 */
  surface: '#FFFFFF',
  /** 对方聊天气泡底 */
  peerBubble: '#EBECED',
  /** 搜索框底 */
  search: '#F2F2F2',
  /** 第一栏选中 */
  sidebarSelected: '#FAFBFD',
  /** 第二栏会话选中 */
  convSelected: '#E6EDFB',
  /** 会话行悬停 */
  convHover: '#EAEBEB',
  /** 错误、删除、红点 */
  danger: '#EC412B',
  /** 品牌色 */
  primary: '#5AB2AC',
  primaryPressed: '#4EA39E',
  primarySoft: '#EDF8F6',
  /** 收藏星标 */
  favorite: '#F5A623',
  /** 主动触达黄点 */
  proactive: '#FACC15',
  /** 文本链接 */
  link: '#1677ff',
  success: '#15803D',
  warning: '#B45309',
  warningSoft: '#FFF1E0',
  info: '#0369A1',
  imagePlaceholder: '#E2E4E8',
  videoBg: '#1A1C1E',
  videoOverlay: 'rgba(18, 24, 32, 0.5)',
  videoOverlayStrong: 'rgba(18, 24, 32, 0.62)',
  voiceBg: '#E7F0FF',
  voice: '#355C9A',
  voiceRail: '#8AA6D4',
  voicePressed: '#2E528A',
  voiceHandleShadow: '0 1px 4px rgba(53, 92, 154, 0.38)',
  onPrimarySoft: 'rgba(255, 255, 255, 0.2)',
  filePdfBg: '#FDECEA',
  filePdf: '#EC412B',
  fileWordBg: '#E8F1FB',
  fileWord: '#2B579A',
  fileExcelBg: '#E7F6EE',
  fileExcel: '#217346',
  filePptBg: '#FDEEE8',
  filePpt: '#C43E1C',
  fileZipBg: '#F4F0FF',
  fileZip: '#7C3AED',
  fileImageBg: '#EEF6FF',
  fileImage: '#2563EB',
} as const;

/**
 * 各页/区域背景。当前多数等于 bg / surface，拆开是为了以后能单独改。
 */
export const webPageBg = {
  login: '#F0FDFA',
  register: '#F0FDFA',
  index: webColor.bg,
  shell: webColor.sidebar,
  main: webColor.pane,
  page: webColor.bg,
  pageHeader: webColor.pane,
  conversationList: webColor.pane,
  actorList: webColor.pane,
  chatRoom: webColor.chatBg,
  chatHeader: webColor.pane,
  chatComposer: webColor.pane,
  profile: webColor.pane,
  performance: webColor.bg,
  performanceSettlement: webColor.bg,
  salaryDetails: webColor.bg,
  annotators: webColor.pane,
  annotatorSessions: webColor.pane,
  assignActors: webColor.bg,
  actorInfo: webColor.bg,
  favorites: webColor.bg,
  customStickers: webColor.bg,
  resetPassword: webColor.bg,
} as const;

/**
 * 字号。改这里即可全局换字号，页面不要再写死 px。
 * webType 已引用这些值；图标/角标等单独用 webFontSize.xxx。
 */
export const webFontSize = {
  /** 语音播放图标 */
  voicePlayIcon: 10,
  /** 视频时长角标 */
  videoDuration: 11,
  /** 副标题、时间、提示、语音时长 */
  sm: 12,
  pageSubtitle: 12,
  subLabel: 11,
  timestamp: 10,
  hint: 12,
  fileSize: 12,
  voiceTime: 12,
  favoriteIcon: 12,
  /** 聊天页右上角更多（省略号） */
  moreIcon: 25,
  /** 输入框下方工具按钮 */
  composerActionIcon: 18,
  /** 表情面板格子 */
  emojiGlyph: 22,
  emojiPure: 25,
  emojiPreview: 14,
  emojiTabIcon: 18,
  /** 文件名、默认正文、输入占位 */
  md: 14,
  fileName: 14,
  placeholder: 14,
  /** 列表主标题 */
  nameLabel: 14,
  /** 聊天导航、区块标题、侧栏收起、弹窗标题 */
  lg: 16,
  chatNavTitle: 15,
  sectionTitle: 15,
  appNameCollapsed: 16,
  modalTitle: 16,
  /** 弹窗说明/副标题 */
  modalSubtitle: 13,
  /** 页标题、侧栏应用名、文件图标 */
  xl: 18,
  appName: 18,
  pageTitle: 16,
  paneTitle: 16,
  fileIcon: 18,
  /** 视频封面播放图标 */
  videoPlayIcon: 28,
  /** 登录/启动页大标题 */
  authTitle: 30,
  /** 空状态大图标 */
  emptyIcon: 48,
} as const;

function typeStyle(
  fontSize: number,
  lineHeight: number,
  extra?: CSSProperties,
): CSSProperties {
  return { margin: 0, fontSize, lineHeight: `${lineHeight}px`, ...extra };
}

/** 标题/副标题字样。用法：style={webType.nameLabel} */
export const webType = {
  appName: typeStyle(webFontSize.appName, 24, { fontWeight: 600, color: webColor.text }),
  authTitle: typeStyle(webFontSize.authTitle, 38, { fontWeight: 600, color: webColor.text }),
  pageTitle: typeStyle(webFontSize.pageTitle, 26, { fontWeight: 450, color: webColor.text }),
  pageSubtitle: typeStyle(webFontSize.pageSubtitle, 18, { fontWeight: 400, color: webColor.textDetail }),
  paneTitle: typeStyle(webFontSize.paneTitle, 24, { fontWeight: 450, color: webColor.text }),
  chatNavTitle: typeStyle(webFontSize.chatNavTitle, 24, { fontWeight: 600, color: webColor.text }),
  sectionTitle: typeStyle(webFontSize.sectionTitle, 24, { fontWeight: 600, color: webColor.text }),
  modalTitle: typeStyle(webFontSize.modalTitle, 24, { fontWeight: 400, color: webColor.text }),
  modalSubtitle: typeStyle(webFontSize.modalSubtitle, 20, {
    fontWeight: 400,
    color: webColor.textDetail,
    marginBottom: 12,
  }),
  nameLabel: typeStyle(webFontSize.nameLabel, 20, { fontWeight: 400, color: webColor.nameLabel }),
  subLabel: typeStyle(webFontSize.subLabel, 16, { fontWeight: 400, color: webColor.subLabel }),
  timestamp: typeStyle(webFontSize.timestamp, 14, { fontWeight: 400, color: webColor.timestamp }),
  hint: typeStyle(webFontSize.hint, 16, { fontWeight: 400, color: webColor.textRemind }),
  fileName: typeStyle(webFontSize.fileName, 20, { fontWeight: 500 }),
  fileSize: typeStyle(webFontSize.fileSize, 16),
  placeholder: typeStyle(webFontSize.placeholder, 22, {
    fontWeight: 400,
    color: webColor.placeholder,
  }),
} as const;

/** 弹窗右上角关闭：去掉浏览器默认 button 边框方框 */
export const webModalCloseStyle: CSSProperties = {
  appearance: 'none',
  WebkitAppearance: 'none',
  border: 'none',
  outline: 'none',
  boxShadow: 'none',
  background: 'transparent',
  width: 22,
  height: 22,
  minWidth: 22,
  minHeight: 22,
  padding: 0,
  color: webColor.subLabel,
};

/** 内容区通用内边距，可叠 webPageBg */
export const webLayout = {
  pageBody: { padding: 20, overflow: 'auto', height: '100%' } satisfies CSSProperties,
  cardShadow: '0 12px 40px rgba(26,21,16,0.08)',
  /** 会话 name 与最后一条消息的间距 */
  convNamePreviewGap: 2.5,
  /** 选中/hover 底相对列表左右缩进 */
  convRowSelectedInset: 5,
  /** 内容相对选中底的左右内边距（时间、红黄点等） */
  convRowContentInset: 5,
  /** 会话列表 cell 上下内边距 */
  convRowPadY: 8,
  /** 会话列表 cell 左右内边距 = 选中底缩进 + 内容内边距（左右对称） */
  convRowPadX: 10,
  convRowPadRight: 10,
  /** 会话列表 cell 额外底间距（选中底与下一行空隙） */
  convRowPadBottom: 0,
  /**
   * 会话列表 cell 固定高度（border-box）。
   * 行高必须恒定，列表的窗口化渲染才能按 index 直接算偏移。
   */
  convRowHeight: 52,
  /** 会话列表头像边长（Actor 列表同尺寸） */
  convAvatarSize: 30,
  /** 输入框下方工具按钮边长 */
  composerActionBtn: 40,
  composerInputMin: 56,
  composerInputMax: 160,
  /** 表情弹出面板 */
  emojiPanelWidth: 420,
  emojiPanelHeight: 340,
  emojiGridCols: 10,
  emojiTabBar: 44,
  emojiSticker: 56,
  /** 桌面四栏占比（相对整窗）：Actor / 会话列表，剩余为聊天区；侧栏固定像素 */
  pane1Pct: 13,
  pane2Pct: 14,
  pane3Pct: 18,
  /** 第一～三栏拖动调宽上下限（px） */
  paneSiderMin: 56,
  paneSiderMax: 180,
  /** Actor 列可收到仅头像：行左右内边距 + 头像边长 */
  paneActorMin: 50,
  paneActorMax: 420,
  /** 小于等于此宽度时 Actor 列只显示头像 */
  paneActorCompactMax: 108,
  /** 标注员列表仍用原先下限 */
  paneAnnotatorMin: 180,
  paneConvMin: 190,
  paneConvMax: 560,
  paneChatMin: 360,
  /** 桌面：侧栏固定宽度 */
  siderWidth: 80,
  siderWidthMd: 80,
  siderWidthSm: 80,
  /** 桌面：Actor 列表宽（回退） */
  actorListWidth: 280,
  actorListWidthMd: 240,
  actorListWidthSm: 200,
  /** 桌面：会话/标注员列表宽（回退） */
  chatListWidth: 370,
  chatListWidthMd: 310,
  chatListWidthSm: 250,
  annotatorListWidth: 267,
  annotatorListWidthMd: 213,
  annotatorListWidthSm: 173,
  /** 标注员页：内嵌聊天时中间会话列表栏宽 */
  annotatorSessionListWidthCompact: 280,
  annotatorSessionListWidthCompactMd: 240,
  annotatorSessionListWidthCompactSm: 200,
  /** 小大屏断点（px，与 WEB_DESKTOP_MIN_WIDTH 衔接） */
  compactMaxWidth: 1199,
  compactTightMaxWidth: 960,
} as const;

export const qinghuiAntdTheme: ThemeConfig = {
  token: {
    colorPrimary: webColor.primary,
    colorSuccess: webColor.success,
    colorWarning: webColor.warning,
    colorError: webColor.danger,
    colorInfo: webColor.info,
    colorBgLayout: webColor.bg,
    colorBgContainer: webColor.surface,
    colorBgElevated: webColor.surface,
    colorBgContainerDisabled: webColor.separator,
    colorBorder: webColor.separator,
    colorBorderSecondary: webColor.separator,
    colorSplit: webColor.separator,
    colorText: webColor.text,
    colorTextSecondary: webColor.textDetail,
    colorTextTertiary: webColor.textRemind,
    colorTextQuaternary: webColor.textRemind,
    colorTextPlaceholder: webColor.placeholder,
    colorTextDisabled: webColor.textRemind,
    fontSize: webFontSize.md,
    borderRadius: 10,
    fontFamily:
      '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif',
  },
  components: {
    Layout: {
      siderBg: 'var(--qh-sider-bg)',
      headerBg: webPageBg.pageHeader,
      bodyBg: webPageBg.main,
    },
    Menu: {
      itemBg: 'transparent',
      itemHoverBg: webColor.sidebarSelected,
      itemActiveBg: webColor.sidebarSelected,
      itemSelectedBg: webColor.sidebarSelected,
      itemSelectedColor: webColor.nameLabel,
    },
  },
};
