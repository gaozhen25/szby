import { useState } from "react";

import ThemeToggle from "./ThemeToggle";

const defaultLogin = { email: "", password: "" };

export default function AuthScreen({ app, theme, setTheme }) {
  const [loginForm, setLoginForm] = useState(defaultLogin);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const displayError = error || app.error || "";

  async function submitLogin(event) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      await app.login(loginForm);
    } catch (err) {
      setError(err.message || "登录失败");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-shell">
      <div className="auth-theme-toggle">
        <ThemeToggle theme={theme} onChange={setTheme} />
      </div>
      <div className="auth-card">
        <div className="brand-mark auth-mark">✦</div>
        <h1>繁星AI内容生产平台</h1>
        <p className="muted">企业内容运营工作台，请使用平台 toB 账号登录。</p>
        <form className="form-card auth-form" onSubmit={submitLogin}>
          <input
            placeholder="邮箱"
            value={loginForm.email}
            onChange={(event) => setLoginForm({ ...loginForm, email: event.target.value })}
          />
          <div className="auth-password-field">
            <input
              placeholder="密码"
              type={showPassword ? "text" : "password"}
              value={loginForm.password}
              onChange={(event) => setLoginForm({ ...loginForm, password: event.target.value })}
            />
            <button
              type="button"
              className="auth-password-toggle"
              aria-label={showPassword ? "隐藏密码" : "显示密码"}
              aria-pressed={showPassword}
              onClick={() => setShowPassword((current) => !current)}
            >
              {showPassword ? (
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M3 3l18 18" />
                  <path d="M10.6 10.6a2 2 0 0 0 2.8 2.8" />
                  <path d="M9.9 5.1A10.5 10.5 0 0 1 12 5c5 0 9.3 3.1 11 7-.5 1.2-1.2 2.3-2.1 3.2" />
                  <path d="M6.1 6.1C4.6 7.2 3.4 8.7 2.5 10.5c1.7 3.9 6 7 11.5 7 1.3 0 2.5-.2 3.6-.5" />
                </svg>
              ) : (
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M2.5 12C4.2 8.1 7.8 5.5 12 5.5S19.8 8.1 21.5 12C19.8 15.9 16.2 18.5 12 18.5S4.2 15.9 2.5 12Z" />
                  <circle cx="12" cy="12" r="3" />
                </svg>
              )}
            </button>
          </div>
          <button className="btn btn-primary" type="submit" disabled={submitting}>
            {submitting ? "登录中..." : "立即登录"}
          </button>
        </form>

        {displayError ? <p className="auth-error">{displayError}</p> : null}
      </div>
    </div>
  );
}
