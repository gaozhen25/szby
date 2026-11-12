import { useEffect, useRef, useState } from "react";
import ModalOverlay from "../../components/ModalOverlay";

const INITIAL_FORM = {
  profileUrl: "",
  similarityReason: "用户手动添加",
};

function safeImageUrl(value) {
  try {
    const parsed = new URL(String(value || ""));
    return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : "";
  } catch {
    return "";
  }
}

function formatCount(value) {
  const count = Number(value);
  return Number.isFinite(count) ? new Intl.NumberFormat("zh-CN").format(count) : "0";
}

export default function SimilarAccountModal({ open, onClose, onResolve, onSubmit }) {
  const [form, setForm] = useState(INITIAL_FORM);
  const [resolvedAccount, setResolvedAccount] = useState(null);
  const [resolving, setResolving] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const dialogRef = useRef(null);
  const busyRef = useRef(false);
  const busy = resolving || submitting;
  busyRef.current = busy;

  useEffect(() => {
    if (!open) return undefined;
    setForm(INITIAL_FORM);
    setResolvedAccount(null);
    setError("");
    const previouslyFocused = document.activeElement;
    window.setTimeout(() => dialogRef.current?.querySelector("input")?.focus(), 0);
    const handleKeyDown = (event) => {
      if (event.key === "Escape" && !busyRef.current) onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      if (previouslyFocused instanceof HTMLElement) previouslyFocused.focus();
    };
  }, [onClose, open]);

  if (!open) return null;

  const update = (key) => (event) => {
    setForm((current) => ({ ...current, [key]: event.target.value }));
    setError("");
  };

  const resolveAccount = async (event) => {
    event.preventDefault();
    setResolving(true);
    setError("");
    try {
      const account = await onResolve(form.profileUrl);
      setResolvedAccount(account);
    } catch (resolveError) {
      setError(resolveError.message || "未能解析该账号链接，请检查后重试");
    } finally {
      setResolving(false);
    }
  };

  const confirmAccount = async () => {
    if (!resolvedAccount) return;
    setSubmitting(true);
    setError("");
    try {
      await onSubmit({ ...resolvedAccount, similarityReason: form.similarityReason });
      onClose();
    } catch (submitError) {
      setError(submitError.message || "添加失败，请稍后重试");
    } finally {
      setSubmitting(false);
    }
  };

  const avatarUrl = safeImageUrl(resolvedAccount?.avatarUrl);
  return (
    <ModalOverlay className="report-similar-modal-overlay">
      <section ref={dialogRef} className="modal report-similar-modal" role="dialog" aria-modal="true" aria-labelledby="report-similar-modal-title">
        <h3 id="report-similar-modal-title">{resolvedAccount ? "确认相似账号" : "添加相似账号"}</h3>
        {!resolvedAccount ? (
          <>
            <p>粘贴公开账号主页，系统会自动识别平台并获取博主信息。</p>
            <form onSubmit={resolveAccount}>
              <label>
                <span className="field-label">公开账号主页</span>
                <input type="url" required value={form.profileUrl} onChange={update("profileUrl")} placeholder="粘贴小红书、抖音或快手主页链接" />
              </label>
              <label>
                <span className="field-label">相似原因</span>
                <textarea required maxLength={500} rows={3} value={form.similarityReason} onChange={update("similarityReason")} />
              </label>
              {error ? <p className="report-similar-form-error" role="alert">{error}</p> : null}
              <div className="modal-actions">
                <button type="button" className="btn" disabled={busy} onClick={onClose}>取消</button>
                <button type="submit" className="btn btn-primary" disabled={busy}>{resolving ? "正在解析…" : "确定"}</button>
              </div>
            </form>
          </>
        ) : (
          <div className="report-similar-resolved">
            <p>请确认解析到的博主是否正确：</p>
            <div className="report-similar-profile-card">
              {avatarUrl ? <img src={avatarUrl} alt="" /> : <span className="report-similar-avatar-fallback">{resolvedAccount.name?.slice(0, 1) || "?"}</span>}
              <div>
                <h4>{resolvedAccount.name}</h4>
                <span className="platform-readable-tag">{resolvedAccount.platform}</span>
                {resolvedAccount.description ? <p>{resolvedAccount.description}</p> : null}
                {resolvedAccount.ipLocation ? <small>IP 属地：{resolvedAccount.ipLocation}</small> : null}
              </div>
            </div>
            <div className="report-similar-resolved-metrics">
              <span><b>{formatCount(resolvedAccount.followers)}</b>粉丝</span>
              <span><b>{formatCount(resolvedAccount.follows)}</b>关注</span>
              <span><b>{formatCount(resolvedAccount.contentCount)}</b>作品</span>
              <span><b>{formatCount(resolvedAccount.totalLikes)}</b>获赞</span>
            </div>
            {error ? <p className="report-similar-form-error" role="alert">{error}</p> : null}
            <div className="modal-actions">
              <button type="button" className="btn" disabled={busy} onClick={() => { setResolvedAccount(null); setError(""); }}>不是他，返回修改</button>
              <button type="button" className="btn btn-primary" disabled={busy} onClick={confirmAccount}>{submitting ? "正在添加…" : "是他"}</button>
            </div>
          </div>
        )}
      </section>
    </ModalOverlay>
  );
}
