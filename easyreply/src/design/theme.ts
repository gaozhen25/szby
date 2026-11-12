import { Tokens } from "./tokens";

export const lightTheme = {
  ...Tokens.color,
} as const;

export type AppTheme = typeof lightTheme;

