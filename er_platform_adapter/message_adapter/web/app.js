const platformLabels = {
  boss: "BOSS 直聘",
  douyin: "抖音",
  rednote: "小红书",
  wechat: "微信",
  wecom: "企业微信",
};

const workerLabels = {
  ready: "运行中",
  starting: "正在启动",
  retrying: "等待重连",
  offline: "未启动",
  stopped: "已停止",
};

let controlToken = "";
let toastTimer = null;

class ApiError extends Error {
  constructor(payload, status) {
    super(payload.error || `请求失败（${status}）`);
    this.payload = payload;
    this.status = status;
  }
}

function showToast(message, isError = false) {
  const toast = document.querySelector("#toast");
  toast.textContent = message;
  toast.classList.toggle("is-error", isError);
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toast.hidden = true;
  }, 4200);
}

async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.method && options.method !== "GET") {
    headers["Content-Type"] = "application/json";
    headers["X-Adapter-Control"] = controlToken;
  }
  const response = await fetch(path, { ...options, headers, cache: "no-store" });
  const payload = await response.json();
  if (!response.ok) throw new ApiError(payload, response.status);
  return payload;
}

function stateView(platform, upstreamSync) {
  const login = platform.login || {};
  const syncFailed = upstreamSync.state === "error" && platform.credential_present;
  if (login.state === "starting" || login.state === "waiting") {
    return { label: "登录中", className: "is-working" };
  }
  if (platform.online) return { label: "在线", className: "is-online" };
  if (syncFailed || login.state === "error" || (platform.credential_present && platform.state === "retrying")) {
    return { label: "连接异常", className: "is-error" };
  }
  if (platform.credential_present) return { label: "连接中", className: "is-working" };
  return { label: "未登录", className: "is-offline" };
}

function updatePlatform(name, platform, localLoggedIn, upstreamSync) {
  const card = document.querySelector(`[data-platform="${name}"]`);
  const view = stateView(platform, upstreamSync);
  const state = card.querySelector('[data-role="state"]');
  state.className = `platform-state ${view.className}`;
  state.querySelector('[data-role="state-label"]').textContent = view.label;
  card.classList.toggle("is-online", platform.online);
  card.classList.toggle("is-locked", !localLoggedIn);
  const uid = platform.platform_actor_id || "";
  card.querySelector('[data-role="uid"]').textContent = uid || "—";
  card.querySelector('[data-role="worker"]').textContent = workerLabels[platform.state] || platform.state || "未知";

  const login = platform.login || {};
  const hostLogin = card.dataset.loginMode === "host";
  let message = !localLoggedIn
    ? "请先使用上方激活码登录本机工作区。"
    : hostLogin
      ? "按接入文档在小主机启动客户端，出现「启动成功」后再点登录。"
      : "登录后会在当前本机工作区持续接收和发送消息。";
  if (localLoggedIn && (login.state === "starting" || login.state === "waiting" || login.state === "error")) {
    message = login.message || message;
  } else if (localLoggedIn && platform.online) {
    message = "账号连接正常，收发消息可用。";
  } else if (localLoggedIn && platform.last_error) {
    message = platform.last_error;
  } else if (localLoggedIn && platform.credential_present) {
    message = "已保存登录信息，正在连接消息服务。";
  }
  card.querySelector('[data-role="message"]').textContent = message;

  const busy = login.state === "starting" || login.state === "waiting";
  const loginButton = card.querySelector('[data-action="login"]');
  loginButton.disabled = !localLoggedIn || busy;
  loginButton.textContent = hostLogin
    ? busy ? "正在检查…" : "登录"
    : busy ? "等待扫码…" : platform.credential_present ? "重新登录" : "扫码登录";
  const logoutButton = card.querySelector('[data-action="logout"]');
  if (logoutButton) {
    logoutButton.hidden = !platform.credential_present && !busy;
    logoutButton.disabled = !localLoggedIn || busy;
  }
  const resetButton = card.querySelector('[data-action="reset"]');
  if (resetButton) {
    resetButton.hidden = !platform.platform_actor_id || busy;
    resetButton.disabled = !localLoggedIn || busy;
  }
}

function updateLocalAccount(localAccount, upstreamSync) {
  const loggedIn = Boolean(localAccount.logged_in);
  const input = document.querySelector("#activation-code");
  const loginButton = document.querySelector("#local-account-login");
  const logoutButton = document.querySelector("#local-account-logout");
  const actions = document.querySelector("#local-account-actions");
  const note = document.querySelector("#local-account-note");

  if (loggedIn) input.value = localAccount.activation_code || "";
  input.readOnly = loggedIn;
  loginButton.hidden = loggedIn;
  logoutButton.hidden = !loggedIn;
  actions.hidden = !loggedIn;

  if (!loggedIn) {
    note.textContent = "请输入激活码进入本机工作区。未知激活码会在确认后创建新工作区。";
    return;
  }
  const messages = {
    synced: "本地工作区已登录，并已同步到轻回。",
    syncing: "本地工作区已登录，正在同步到轻回…",
    pending: "本地工作区已登录。登录平台后会在后台同步到轻回。",
    error: upstreamSync.message || "同步轻回失败",
  };
  note.textContent = messages[upstreamSync.state] || upstreamSync.message || "本地工作区已登录。";
}

function render(state) {
  document.querySelector("#service-label").textContent = "本机服务运行中";
  const loggedIn = Boolean(state.local_account && state.local_account.logged_in);
  const upstreamSync = state.upstream_sync || {};
  updateLocalAccount(state.local_account || {}, upstreamSync);
  for (const name of Object.keys(platformLabels)) {
    if (state.platforms[name]) updatePlatform(name, state.platforms[name], loggedIn, upstreamSync);
  }
}

async function refreshState({ quiet = true } = {}) {
  try {
    render(await request("/api/state"));
  } catch (error) {
    document.querySelector("#service-label").textContent = "本机服务连接失败";
    if (!quiet) showToast(error.message, true);
  }
}

async function platformAction(platform, action) {
  const card = document.querySelector(`[data-platform="${platform}"]`);
  card.setAttribute("aria-busy", "true");
  try {
    await request(`/api/platforms/${platform}/${action}`, { method: "POST", body: "{}" });
    const hostLogin = card.dataset.loginMode === "host";
    const text = hostLogin ? `${platformLabels[platform]}正在检查本机客户端` : `${platformLabels[platform]}扫码窗口正在打开`;
    showToast(action === "login" ? text : `${platformLabels[platform]}已退出`);
    await refreshState({ quiet: false });
  } catch (error) {
    showToast(error.message, true);
  } finally {
    card.removeAttribute("aria-busy");
  }
}

async function copyText(text, successMessage) {
  try {
    await navigator.clipboard.writeText(text);
    showToast(successMessage);
  } catch (error) {
    showToast(error.message || "复制失败", true);
  }
}

function confirmPlatformSwitch(platform, uid) {
  const dialog = document.querySelector("#switch-dialog");
  const input = document.querySelector("#switch-dialog-input");
  document.querySelector("#switch-dialog-text").textContent =
    `更换账号会归档当前 ${platformLabels[platform]} 在这个工作区内的状态。`;
  document.querySelector("#switch-dialog-uid").textContent = uid;
  input.value = "";
  dialog.hidden = false;
  input.focus();
  return new Promise((resolve) => {
    const finish = (value) => {
      dialog.hidden = true;
      dialog.removeEventListener("click", onBackdrop);
      document.querySelector("#switch-dialog-copy").removeEventListener("click", onCopy);
      document.querySelector("#switch-dialog-cancel").removeEventListener("click", onCancel);
      document.querySelector("#switch-dialog-confirm").removeEventListener("click", onConfirm);
      input.removeEventListener("keydown", onKeydown);
      resolve(value);
    };
    const onCopy = () => copyText(uid, `已复制${platformLabels[platform]} UID`);
    const onCancel = () => finish(null);
    const onConfirm = () => finish(input.value);
    const onBackdrop = (event) => {
      if (event.target === dialog) finish(null);
    };
    const onKeydown = (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        finish(input.value);
      } else if (event.key === "Escape") {
        finish(null);
      }
    };
    document.querySelector("#switch-dialog-copy").addEventListener("click", onCopy);
    document.querySelector("#switch-dialog-cancel").addEventListener("click", onCancel);
    document.querySelector("#switch-dialog-confirm").addEventListener("click", onConfirm);
    dialog.addEventListener("click", onBackdrop);
    input.addEventListener("keydown", onKeydown);
  });
}

async function resetPlatform(platform) {
  const card = document.querySelector(`[data-platform="${platform}"]`);
  const uid = card.querySelector('[data-role="uid"]').textContent.trim();
  if (!uid || uid === "—") return showToast("当前平台没有可确认的 UID", true);
  const confirmation = await confirmPlatformSwitch(platform, uid);
  if (confirmation === null) return;
  if (confirmation.trim() !== uid) return showToast("输入的 UID 与当前绑定 UID 不一致", true);
  card.setAttribute("aria-busy", "true");
  try {
    await request(`/api/platforms/${platform}/reset`, {
      method: "POST",
      body: JSON.stringify({ confirm_uid: uid }),
    });
    showToast(`${platformLabels[platform]}旧账号已归档，请重新扫码`);
    await refreshState({ quiet: false });
  } catch (error) {
    showToast(error.message, true);
  } finally {
    card.removeAttribute("aria-busy");
  }
}

function openDocs(platform) {
  window.open(`/docs/${platform}`, "_blank", "noopener");
}

async function downloadDiagnostics() {
  try {
    const response = await fetch("/api/diagnostics/download", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Adapter-Control": controlToken },
      body: "{}",
      cache: "no-store",
    });
    if (!response.ok) throw new Error((await response.json()).error || `请求失败（${response.status}）`);
    const blob = await response.blob();
    const match = (response.headers.get("Content-Disposition") || "").match(/filename="([^"]+)"/);
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = match ? match[1] : "adapter-diagnostics.zip";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(link.href);
    showToast("诊断包已下载");
  } catch (error) {
    showToast(error.message, true);
  }
}

async function loginLocalAccount(code, create = false) {
  return request("/api/local-account/login", {
    method: "POST",
    body: JSON.stringify({ activation_code: code, create }),
  });
}

async function initialize() {
  try {
    controlToken = (await request("/api/session")).control_token;
  } catch (error) {
    showToast("无法建立本机控制会话", true);
    return;
  }

  document.querySelectorAll("[data-platform]").forEach((card) => {
    const platform = card.dataset.platform;
    card.querySelector('[data-action="login"]').addEventListener("click", () => platformAction(platform, "login"));
    const logout = card.querySelector('[data-action="logout"]');
    if (logout) logout.addEventListener("click", () => {
      if (window.confirm(`确定退出${platformLabels[platform]}吗？当前工作区的消息状态会保留。`)) {
        platformAction(platform, "logout");
      }
    });
    const docs = card.querySelector('[data-action="docs"]');
    if (docs) docs.addEventListener("click", () => openDocs(platform));
    const reset = card.querySelector('[data-action="reset"]');
    if (reset) reset.addEventListener("click", () => resetPlatform(platform));
  });

  document.querySelector("#local-account-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = document.querySelector("#activation-code");
    const code = input.value.trim();
    if (code.length < 4) return showToast("请输入有效的激活码", true);
    try {
      await loginLocalAccount(code);
      showToast("已进入本机工作区");
    } catch (error) {
      if (error.payload && error.payload.code === "workspace_not_found" && error.payload.can_create) {
        const confirmed = window.confirm("本机没有这个激活码的记录。是否为它创建一个新的独立工作区？");
        if (!confirmed) return;
        try {
          await loginLocalAccount(code, true);
          showToast("已创建并进入新的本机工作区");
        } catch (createError) {
          return showToast(createError.message, true);
        }
      } else {
        return showToast(error.message, true);
      }
    }
    await refreshState({ quiet: false });
  });

  document.querySelector("#local-account-logout").addEventListener("click", async () => {
    if (!window.confirm("确定切换激活码吗？当前工作区会完整保留，所有平台连接会暂时停止。")) return;
    try {
      await request("/api/local-account/logout", { method: "POST", body: "{}" });
      document.querySelector("#activation-code").value = "";
      showToast("已退出本地账号");
      await refreshState({ quiet: false });
    } catch (error) {
      showToast(error.message, true);
    }
  });

  document.querySelector("#local-account-reset").addEventListener("click", async () => {
    const confirmation = window.prompt(
      "这会归档当前工作区的全部平台凭证、Profile、消息状态和日志。激活码与设备身份会保留。\n请输入“重置当前工作区”确认：",
      "",
    );
    if (confirmation === null) return;
    try {
      await request("/api/local-account/reset", {
        method: "POST",
        body: JSON.stringify({ confirmation: confirmation.trim() }),
      });
      showToast("当前工作区已归档并重置");
      await refreshState({ quiet: false });
    } catch (error) {
      showToast(error.message, true);
    }
  });

  document.querySelector("#upstream-sync").addEventListener("click", async () => {
    try {
      const result = await request("/api/local-account/sync", { method: "POST", body: "{}" });
      showToast(result.state === "synced" ? "已同步到轻回" : "已安排后台同步");
      await refreshState({ quiet: false });
    } catch (error) {
      showToast(error.message, true);
      await refreshState();
    }
  });

  document.querySelector("#diagnostics-download").addEventListener("click", downloadDiagnostics);
  await refreshState({ quiet: false });
  window.setInterval(() => refreshState(), 2000);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refreshState();
  });
}

initialize();
