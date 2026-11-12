export const THEME_STORAGE_KEY = "starx_theme";
export const THEMES = ["dark", "light"];
export const DEFAULT_THEME = "dark";

export function normalizeTheme(value) {
  return THEMES.includes(value) ? value : DEFAULT_THEME;
}

export function getStoredTheme() {
  if (typeof window === "undefined") return DEFAULT_THEME;
  try {
    return normalizeTheme(window.localStorage.getItem(THEME_STORAGE_KEY));
  } catch {
    return DEFAULT_THEME;
  }
}

export function applyTheme(theme) {
  const next = normalizeTheme(theme);
  if (typeof document !== "undefined") {
    document.documentElement.dataset.theme = next;
    document.documentElement.style.colorScheme = next;
  }
  if (typeof window !== "undefined") {
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // Ignore quota / private-mode write failures.
    }
  }
  return next;
}
