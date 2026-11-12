export default function ThemeToggle({ theme, onChange, className = "" }) {
  return (
    <div className={`theme-toggle ${className}`.trim()} role="group" aria-label="主题">
      <button
        type="button"
        className={theme === "dark" ? "active" : ""}
        aria-pressed={theme === "dark"}
        onClick={() => onChange("dark")}
      >
        深色
      </button>
      <button
        type="button"
        className={theme === "light" ? "active" : ""}
        aria-pressed={theme === "light"}
        onClick={() => onChange("light")}
      >
        浅色
      </button>
    </div>
  );
}
