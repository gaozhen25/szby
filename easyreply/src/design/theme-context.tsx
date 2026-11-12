import React, { createContext, useContext, useMemo } from "react";

import { lightTheme, type AppTheme } from "./theme";

const ThemeContext = createContext<AppTheme | null>(null);

export function ThemeProvider(props: { children: React.ReactNode }) {
  const value = useMemo(() => lightTheme, []);
  return <ThemeContext.Provider value={value}>{props.children}</ThemeContext.Provider>;
}

export function useTheme(): AppTheme {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme 必须在 ThemeProvider 内使用");
  return ctx;
}

