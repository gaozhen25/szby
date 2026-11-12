import { useCallback, useEffect, useState } from "react";

import { applyTheme, getStoredTheme } from "../utils/theme";

export function useTheme() {
  const [theme, setThemeState] = useState(() => getStoredTheme());

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const setTheme = useCallback((next) => {
    setThemeState(applyTheme(next));
  }, []);

  const toggleTheme = useCallback(() => {
    setThemeState((current) => applyTheme(current === "light" ? "dark" : "light"));
  }, []);

  return { theme, setTheme, toggleTheme };
}
