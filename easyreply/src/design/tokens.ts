import { Platform } from "react-native";

export const Tokens = {
  color: {
    // Surfaces — warm paper + ink (「青辉」墨韵青釉)
    bg: "#F3F0E8",
    surface: "#FFFCF7",
    surface2: "#F2EDE4",

    // Text
    text: "#121820",
    textMuted: "#5A626C",
    textSubtle: "#7A828C",
    placeholder: "#9A9DA3",

    // Lines
    border: "#E2DCD2",
    divider: "#EBE6DC",

    // Brand — celadon teal, soft & muted on warm paper
    primary: "#5AB2AC",
    primaryPressed: "#4BA29C",
    primarySoft: "#EDF8F6",

    // Atmospheric washes (ScreenCanvas, subtle UI)
    wash1: "#DAF0EC",
    wash2: "#E8E4FF",

    // Status
    success: "#15803D",
    successSoft: "#E6F6EC",
    warning: "#B45309",
    warningSoft: "#FFF1E0",
    danger: "#C41E3A",
    dangerSoft: "#FFE8EC",
    info: "#0369A1",
    infoSoft: "#E0F2FE",
  },

  spacing: {
    0: 0,
    1: 4,
    2: 8,
    3: 12,
    4: 16,
    5: 20,
    6: 24,
    7: 32,
    8: 40,
    9: 48,
  } as const,

  /** 圆角：小控件 / 卡片 / 大容器 / 胶囊按钮 */
  radius: {
    sm: 10,   // 图标底、输入框、小标签
    md: 14,   // 列表卡片、弹窗内容区
    lg: 10,   // 大卡片、分区容器（与 sm 同值，便于语义区分）
    pill: 999, // 全圆角胶囊（按钮、徽章）
  } as const,

  typography: {
    title: { fontSize: 26, lineHeight: 36, letterSpacing: -0.35 },
    subtitle: { fontSize: 18, lineHeight: 25, letterSpacing: -0.15 },
    body: { fontSize: 16, lineHeight: 23 },
    caption: { fontSize: 13, lineHeight: 18 },
    label: { fontSize: 14, lineHeight: 20, letterSpacing: 0.15 },
    /** 一级 Tab 页导航标题 */
    navPrimary: { fontSize: 20, lineHeight: 28, fontWeight: '500' as const },
    /** 二级及以下页导航标题（带返回） */
    navSecondary: { fontSize: 16, lineHeight: 24, fontWeight: '400' as const },
  },

  motion: {
    fast: 120,
    normal: 180,
  } as const,

  shadow: Platform.select({
    ios: {
      card: {
        shadowColor: "#1A1510",
        shadowOpacity: 0.07,
        shadowRadius: 20,
        shadowOffset: { width: 0, height: 10 },
      },
      float: {
        shadowColor: "#1A1510",
        shadowOpacity: 0.11,
        shadowRadius: 30,
        shadowOffset: { width: 0, height: 16 },
      },
    },
    default: {
      card: { elevation: 2 },
      float: { elevation: 4 },
    },
  })!,
} as const;

export type AppColorToken = keyof typeof Tokens.color;
export type AppTextStyleToken = keyof typeof Tokens.typography;

