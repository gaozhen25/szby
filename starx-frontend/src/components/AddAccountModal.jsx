import { useEffect, useState } from "react";

import ModalOverlay from "./ModalOverlay";
import {
  ensureLocalLoginAgent,
  startLocalPlatformLogin,
  waitLocalPlatformLogin,
} from "../api/localLoginAgent.js";
import {
  ACCOUNT_PLATFORM_OPTIONS,
  createAccountProfileFormFromAccount,
  createEmptyAccountProfileForm,
  normalizeAccountProfilePayload,
  validateAccountProfileForm,
  validateAccountProfileStep,
} from "../utils/accountProfileForm";

const goals = [
  { key: "品牌合作", icon: "🤝", label: "品牌合作" },
  { key: "涨粉变现", icon: "📈", label: "涨粉变现" },
  { key: "门店获客", icon: "🏪", label: "门店获客" },
  { key: "私域转化", icon: "👥", label: "私域转化" },
];

export default function AddAccountModal({ app }) {
  const [form, setForm] = useState(createEmptyAccountProfileForm);
  const [step, setStep] = useState(1);
  const [submitting, setSubmitting] = useState(false);
  const [showAdvancedInfo, setShowAdvancedInfo] = useState(true);
  const [loginBusyPlatform, setLoginBusyPlatform] = useState("");
  const [loginHint, setLoginHint] = useState("");
  const [loginHintPlatform, setLoginHintPlatform] = useState("");
  const editingAccount = app.editingAccount || null;
  const isEditing = Boolean(editingAccount?.id);

  useEffect(() => {
    if (app.showAddAccountModal) {
      setForm(editingAccount ? createAccountProfileFormFromAccount(editingAccount) : createEmptyAccountProfileForm());
      setStep(1);
      setSubmitting(false);
      setShowAdvancedInfo(true);
      setLoginBusyPlatform("");
      setLoginHint("");
      setLoginHintPlatform("");
    }
  }, [app.showAddAccountModal, editingAccount]);

  if (!app.showAddAccountModal) return null;

  const closeModal = () => {
    if (submitting || loginBusyPlatform) return;
    app.closeAccountModal?.();
  };

  const requestClose = () => {
    if (submitting || loginBusyPlatform) return;
    if (!window.confirm(isEditing ? "确认关闭？未保存的修改将丢失。" : "确认关闭？已填写的内容将不会保存。")) {
      return;
    }
    closeModal();
  };

  const startBrowserLogin = async (platform) => {
    if (submitting || loginBusyPlatform) return;
    setLoginBusyPlatform(platform);
    setLoginHintPlatform(platform);
    setLoginHint("正在准备本机登录助手…");
    try {
      await ensureLocalLoginAgent({
        onProgress: (msg) => setLoginHint(msg || "正在自动安装/启动本机登录助手…"),
      });
      setLoginHint("正在打开本机浏览器，请在弹出窗口中扫码登录…");
      const started = await startLocalPlatformLogin({ platform, method: "qrcode", headed: true });
      const sessionId = started?.sessionId;
      if (!sessionId) {
        throw new Error(started?.message || "本机助手未返回 sessionId");
      }
      const result = await waitLocalPlatformLogin(sessionId, {
        onUpdate: (status) => {
          if (status?.message) setLoginHint(status.message);
        },
      });
      if (result?.status === "success") {
        const accountId = String(result.accountId || "").trim();
        if (accountId) {
          updatePlatformAccount(platform, accountId);
        }
        setLoginHint(
          accountId
            ? `登录成功，已自动填入账号：${accountId}`
            : "登录成功，账号已绑定到当前邮箱。"
        );
        app.addToast(accountId ? `已获取账号 ${accountId}` : "登录成功", "success");
      } else {
        const message = result?.message || "浏览器登录失败";
        setLoginHint(message);
        const cancelled = /关闭浏览器|登录已取消/.test(message);
        app.addToast(message, cancelled ? "warning" : "error");
      }
    } catch (err) {
      const message = err?.message || "浏览器登录失败";
      setLoginHint(message);
      const cancelled = /关闭浏览器|登录已取消/.test(message);
      app.addToast(message, cancelled ? "warning" : "error");
    } finally {
      setLoginBusyPlatform("");
    }
  };

  const confirm = async () => {
    if (submitting) return;
    const errors = validateAccountProfileForm(form);
    if (errors.length > 0) {
      app.addToast(errors.join("；"), "warning");
      return;
    }
    setSubmitting(true);
    try {
      if (isEditing) {
        await app.updateAccount(editingAccount.id, normalizeAccountProfilePayload(form));
      } else {
        await app.createAccount(normalizeAccountProfilePayload(form));
      }
      setForm(createEmptyAccountProfileForm());
      setStep(1);
    } catch (err) {
      const rawMessage = err?.message || "";
      const message =
        rawMessage === "platform links must cover selected platforms"
          ? "所选平台的账号链接必须全部填写"
          : rawMessage || (isEditing ? "保存失败" : "创建失败");
      app.addToast(message, "warning");
    } finally {
      setSubmitting(false);
    }
  };

  const togglePlatform = (platform) => {
    if (submitting) return;
    const selected = form.platforms.includes(platform)
      ? form.platforms.filter((item) => item !== platform)
      : [...form.platforms, platform].sort(
          (left, right) => ACCOUNT_PLATFORM_OPTIONS.indexOf(left) - ACCOUNT_PLATFORM_OPTIONS.indexOf(right)
        );
    const nextPlatforms = selected.length > 0 ? selected : [platform];
    const nextLinks = nextPlatforms.reduce((result, item) => {
      result[item] = form.accountLinks[item] || "";
      return result;
    }, {});
    const nextPlatformAccounts = nextPlatforms.reduce((result, item) => {
      if (item === "抖音" || item === "小红书") {
        result[item] = form.platformAccounts?.[item] || "";
      }
      return result;
    }, {});
    const nextBenchmarkAccounts = nextPlatforms.reduce((result, item) => {
      if (item === "抖音" || item === "小红书") {
        result[item] = form.benchmarkAccounts?.[item] || "";
      }
      return result;
    }, {});
    const nextPublishSettings = nextPlatforms.reduce((result, item) => {
      result[item] = { androidId: form.publishSettings?.[item]?.androidId || "" };
      return result;
    }, {});
    setForm({
      ...form,
      platforms: nextPlatforms,
      accountLinks: nextLinks,
      platformAccounts: nextPlatformAccounts,
      benchmarkAccounts: nextBenchmarkAccounts,
      publishSettings: nextPublishSettings,
    });
  };

  const updateField = (key, value) => {
    if (submitting) return;
    setForm((prev) => ({ ...prev, [key]: value }));
  };
  const openQuickKnowledgeBaseCreation = () => {
    if (submitting) return;
    app.openKnowledgeBaseModal(null, {
      onCreated: (knowledgeBase) => {
        if (!knowledgeBase?.id) return;
        setForm((prev) => ({ ...prev, knowledgeBaseId: knowledgeBase.id }));
      },
    });
  };
  const updatePlatformLink = (platform, value) => {
    if (submitting) return;
    setForm((prev) => ({ ...prev, accountLinks: { ...prev.accountLinks, [platform]: value } }));
  };
  const updatePlatformAccount = (platform, value) => {
    if (submitting) return;
    setForm((prev) => ({
      ...prev,
      platformAccounts: { ...prev.platformAccounts, [platform]: value },
    }));
  };
  const updateBenchmarkAccount = (platform, value) => {
    if (submitting) return;
    setForm((prev) => ({
      ...prev,
      benchmarkAccounts: { ...(prev.benchmarkAccounts || {}), [platform]: value },
    }));
  };
  const updatePublishAndroidId = (platform, value) => {
    if (submitting) return;
    setForm((prev) => ({
      ...prev,
      publishSettings: {
        ...prev.publishSettings,
        [platform]: { ...(prev.publishSettings?.[platform] || {}), androidId: value },
      },
    }));
  };

  const getAvatarChar = (name) => name ? name.charAt(0) : "?";
  const stepLabels = ["账号基础", "平台与定位", "关联知识库"];
  const bodyLockStyle = submitting ? { pointerEvents: "none", opacity: 0.72 } : undefined;

  return (
    <ModalOverlay aria-busy={submitting}>
      <div className="modal modal-wide account-profile-modal" onClick={(e) => e.stopPropagation()} style={{ width: "min(900px, 94vw)" }}>
        <div className="account-modal-header">
          <h3>{isEditing ? "编辑账号" : "新建账号"}</h3>
          <button
            type="button"
            className="account-modal-close"
            aria-label="关闭"
            disabled={submitting}
            onClick={(e) => {
              e.stopPropagation();
              requestClose();
            }}
          >
            ×
          </button>
        </div>

        {/* Wizard Steps */}
        <div className="wizard-steps">
          {stepLabels.map((label, i) => (
            <div key={label} style={{ display: "flex", alignItems: "center", gap: "var(--space-sm)" }}>
              <div className={`wizard-step ${step === i + 1 ? "active" : step > i + 1 ? "completed" : ""}`}>
                <span className="wizard-step-num">{step > i + 1 ? "✓" : i + 1}</span>
                <span>{label}</span>
              </div>
              {i < stepLabels.length - 1 && <div className={`wizard-connector ${step > i + 1 ? "completed" : ""}`} />}
            </div>
          ))}
        </div>

        {/* Step 1: Account Basics */}
        {step === 1 && (
          <div className="wizard-body" style={bodyLockStyle}>
            <div className="wizard-form">
              <div style={{ marginBottom: "var(--space-md)" }}>
                <h4 style={{ fontSize: "var(--text-md)", fontWeight: 600, color: "var(--text-primary)", marginBottom: "var(--space-xs)" }}>
                  先创建一个账号
                </h4>
                <p style={{ fontSize: "var(--text-sm)", color: "var(--text-muted)" }}>
                  基础信息完善后，可继续设置平台和运营策略
                </p>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-md)" }}>
                <div>
                  <label>账号名称 <span style={{ color: "var(--color-accent-red)" }}>*</span></label>
                  <input value={form.name} onChange={(e) => updateField("name", e.target.value)} placeholder="例如：美妆种草_小红书" disabled={submitting} />
                </div>
                <div>
                  <label>账号类型 <span style={{ color: "var(--color-accent-red)" }}>*</span></label>
                  <select value={form.type} onChange={(e) => updateField("type", e.target.value)} disabled={submitting}>
                    <option value="普通号">普通号</option>
                    <option value="专业号">专业号</option>
                    <option value="企业号">企业号</option>
                  </select>
                </div>
              </div>

              <div>
                <label>账号定位 <span style={{ color: "var(--color-accent-red)" }}>*</span></label>
                <textarea
                  value={form.description}
                  onChange={(e) => updateField("description", e.target.value)}
                  rows="3"
                  placeholder="例如：专注平价美妆测评，帮助用户理性选购"
                  style={{ minHeight: 80 }}
                  disabled={submitting}
                />
                <div style={{ textAlign: "right", fontSize: "var(--text-xs)", color: "var(--text-faint)", marginTop: 4 }}>
                  {form.description.length} / 120
                </div>
              </div>

              <div>
                <label>运营目标</label>
                <div className="goal-cards">
                  {goals.map((g) => (
                    <button
                      key={g.key}
                      type="button"
                      className={`goal-card ${form.purpose === g.key ? "active" : ""}`}
                      onClick={() => updateField("purpose", g.key)}
                      disabled={submitting}
                    >
                      <span className="goal-icon">{g.icon}</span>
                      <span>{g.label}</span>
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Preview Panel */}
            <div className="wizard-preview">
              <h4>创建预览</h4>
              <div className="wizard-account-preview">
                <div className="preview-avatar">{getAvatarChar(form.name || "?")}</div>
                <div className="preview-name">{form.name || "账号名称"}</div>
                <div className="preview-status">待绑定平台</div>
                <div style={{ textAlign: "left", marginTop: "var(--space-lg)" }}>
                  <p style={{ fontSize: "var(--text-xs)", color: "var(--text-muted)", marginBottom: "var(--space-sm)" }}>
                    完成后将包含以下内容
                  </p>
                  <div className="wizard-checklist">
                    <div className="wizard-checklist-item done">
                      <span className="check-icon done">✓</span>
                      <span>账号基础</span>
                    </div>
                    <div className="wizard-checklist-item pending">
                      <span className="check-icon pending">○</span>
                      <span>平台设置</span>
                    </div>
                    <div className="wizard-checklist-item pending">
                      <span className="check-icon pending">○</span>
                      <span>关联知识库</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Step 2: Platform & Positioning */}
        {step === 2 && (
          <div className="wizard-body" style={bodyLockStyle}>
            <div className="wizard-form">
              <div>
                <label>平台 <span style={{ color: "var(--color-accent-red)" }}>*</span></label>
                <div className="pill-group">
                  {ACCOUNT_PLATFORM_OPTIONS.map((platform) => (
                    <button key={platform} type="button" className={`pill ${form.platforms.includes(platform) ? "active" : ""}`} onClick={() => togglePlatform(platform)} disabled={submitting}>
                      {{ 小红书: "📕", 视频号: "💬", 抖音: "🎵", 快手: "⚡" }[platform] || "📱"} {platform}
                    </button>
                  ))}
                </div>
              </div>
              {form.platforms.map((platform) => (
                <div key={platform}>
                  {platform === "抖音" || platform === "小红书" ? (
                    <>
                      <label>{{ 小红书: "📕", 抖音: "🎵" }[platform]} 配置自己的{platform}号</label>
                      <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                        <input
                          style={{ flex: 1 }}
                          value={form.platformAccounts?.[platform] || ""}
                          onChange={(e) => updatePlatformAccount(platform, e.target.value)}
                          placeholder="请登录获取账号"
                          autoComplete="off"
                          disabled={submitting || Boolean(loginBusyPlatform)}
                        />
                        <button
                          type="button"
                          className="btn btn-secondary"
                          disabled={submitting || Boolean(loginBusyPlatform)}
                          onClick={() => startBrowserLogin(platform)}
                          title="需本机运行登录助手后，弹出浏览器扫码"
                        >
                          {loginBusyPlatform === platform ? "登录中…" : "浏览器登录"}
                        </button>
                      </div>
                      <small className="muted">点「浏览器登录」扫码；校验通过后自动填入账号，并绑定到当前邮箱。</small>
                      {loginHint && loginHintPlatform === platform ? (
                        <small className="muted" style={{ display: "block", marginTop: 4 }}>
                          {loginHint}
                        </small>
                      ) : null}
                      <label style={{ marginTop: "var(--space-md)" }}>
                        {{ 小红书: "📕", 抖音: "🎵" }[platform]} 对标博主账号{" "}
                        <span className="muted">（选填）</span>
                      </label>
                      <input
                        value={form.benchmarkAccounts?.[platform] || ""}
                        onChange={(e) => updateBenchmarkAccount(platform, e.target.value)}
                        placeholder={platform === "抖音" ? "填写对标抖音号" : "填写对标小红书号"}
                        autoComplete="off"
                        disabled={submitting}
                      />
                      <small className="muted">填写后将会出现在账号报告中并根据该账号生成相似账号。</small>
                    </>
                  ) : (
                    <>
                      <label>{{ 视频号: "💬", 快手: "⚡" }[platform] || "📱"} {platform}账号链接</label>
                      <input value={form.accountLinks[platform] || ""} onChange={(e) => updatePlatformLink(platform, e.target.value)} placeholder={`请输入${platform}主页链接`} disabled={submitting} />
                    </>
                  )}
                </div>
              ))}
              {form.platforms.filter((p) => p !== "视频号").map((platform) => (
                <div key={platform + "-publish"}>
                  <label>{{ 小红书: "📕", 视频号: "💬", 抖音: "🎵", 快手: "⚡" }[platform] || "📱"} {platform}发布设备 ID</label>
                  <input value={form.publishSettings?.[platform]?.androidId || ""} onChange={(e) => updatePublishAndroidId(platform, e.target.value)} placeholder="可选，发布作品前可再配置" disabled={submitting} />
                </div>
              ))}
              <div className="expandable-section">
                <button
                  className={`expandable-header ${showAdvancedInfo ? "open" : ""}`}
                  type="button"
                  aria-expanded={showAdvancedInfo}
                  disabled={submitting}
                  onClick={() => setShowAdvancedInfo((current) => !current)}
                >
                  <span>高级信息（可选） 行业、受众、城市等可稍后填写</span>
                  <span className="expand-icon">▾</span>
                </button>
                {showAdvancedInfo ? (
                  <div className="expandable-body" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-md)" }}>
                    <div>
                      <label>行业</label>
                      <input value={form.industry} onChange={(e) => updateField("industry", e.target.value)} placeholder="例如：美妆护肤" disabled={submitting} />
                    </div>
                    <div>
                      <label>产品/服务</label>
                      <input value={form.productService} onChange={(e) => updateField("productService", e.target.value)} placeholder="例如：修护精华" disabled={submitting} />
                    </div>
                    <div>
                      <label>目标城市</label>
                      <input value={form.targetCity} onChange={(e) => updateField("targetCity", e.target.value)} placeholder="例如：上海" disabled={submitting} />
                    </div>
                    <div>
                      <label>目标人群</label>
                      <input value={form.targetAudience} onChange={(e) => updateField("targetAudience", e.target.value)} placeholder="例如：25-35岁白领女性" disabled={submitting} />
                    </div>
                  </div>
                ) : null}
              </div>
            </div>
            <div className="wizard-preview">
              <h4>平台设置</h4>
              <p style={{ fontSize: "var(--text-sm)", color: "var(--text-muted)" }}>
                为抖音和小红书配置平台账号。点「浏览器登录」会自动启动本机助手；扫码校验通过后关闭浏览器、自动填入账号，并按邮箱绑定登录态（采集会使用全部已绑定登录态）。
              </p>
            </div>
          </div>
        )}

        {/* Step 3: Knowledge Base */}
        {step === 3 && (
          <div className="wizard-body" style={bodyLockStyle}>
            <div className="wizard-form">
              <div style={{ marginBottom: "var(--space-md)" }}>
                <h4 style={{ fontSize: "var(--text-md)", fontWeight: 600, color: "var(--text-primary)", marginBottom: "var(--space-xs)" }}>
                  关联知识库
                </h4>
                <p style={{ fontSize: "var(--text-sm)", color: "var(--text-muted)" }}>
                  一个账号只能绑定一份知识库
                </p>
              </div>
              <div>
                <label>基础知识库</label>
                <select
                  value={form.knowledgeBaseId}
                  onChange={(e) => updateField("knowledgeBaseId", e.target.value)}
                  disabled={submitting || app.knowledgeBases.length === 0}
                >
                  <option value="">
                    {app.knowledgeBases.length === 0 ? "请先创建基础知识库" : "请选择基础知识库"}
                  </option>
                  {app.knowledgeBases.map((kb) => (
                    <option key={kb.id} value={kb.id}>
                      {kb.name}{kb.productName ? ` · ${kb.productName}` : ""}
                    </option>
                  ))}
                </select>
              </div>
              <button type="button" className="btn" onClick={openQuickKnowledgeBaseCreation} disabled={submitting}>
                快速新建知识库
              </button>
            </div>
            <div className="wizard-preview">
              <h4>关联说明</h4>
              <p style={{ fontSize: "var(--text-sm)", color: "var(--text-muted)" }}>
                关联知识库后，创作内容将自动引用品牌资料，确保内容与品牌调性一致。
              </p>
            </div>
          </div>
        )}

        {/* Footer */}
        <div className="wizard-footer">
          {step === 1 ? (
            <span className="step-indicator">第 1 步，共 3 步</span>
          ) : step === 2 ? (
            <span className="step-indicator">第 2 步，共 3 步</span>
          ) : (
            <span className="draft-status"><span className="check">✓</span> 已保存草稿</span>
          )}
          <div className="wizard-footer-actions">
            <button
              className="btn"
              type="button"
              disabled={submitting}
              onClick={(e) => {
                e.stopPropagation();
                if (submitting) return;
                if (step > 1) setStep(step - 1);
                else requestClose();
              }}
            >
              {step > 1 ? "上一步" : "取消"}
            </button>
            {step < 3 ? (
              <button
                className="btn btn-primary"
                type="button"
                disabled={submitting}
                onClick={(e) => {
                  e.stopPropagation();
                  if (submitting) return;
                  const errors = validateAccountProfileStep(form, step);
                  if (errors.length > 0) {
                    app.addToast(errors.join("；"), "warning");
                    return;
                  }
                  setStep(step + 1);
                }}
              >
                下一步：{stepLabels[step]}
              </button>
            ) : (
              <button
                className="btn btn-primary"
                type="button"
                disabled={submitting}
                aria-busy={submitting}
                onClick={(e) => {
                  e.stopPropagation();
                  confirm();
                }}
              >
                {submitting
                  ? (isEditing ? "保存中…" : "创建中…")
                  : (isEditing ? "保存修改" : "确认创建")}
              </button>
            )}
          </div>
        </div>
      </div>
    </ModalOverlay>
  );
}
