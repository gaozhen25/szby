const API_BASE = import.meta.env?.VITE_API_BASE_URL || "http://127.0.0.1:8000/api/v1";
export { API_BASE };
export const AUTH_SESSION_EXPIRED_EVENT = "starx:auth-session-expired";
let accessToken = typeof window !== "undefined" ? window.localStorage.getItem("starx_token") || "" : "";
let sessionExpiredDispatched = false;

export function getAccessToken() {
  return accessToken;
}

export function setAccessToken(token) {
  accessToken = token;
  if (token) {
    sessionExpiredDispatched = false;
  }
  if (typeof window !== "undefined") {
    if (token) {
      window.localStorage.setItem("starx_token", token);
    } else {
      window.localStorage.removeItem("starx_token");
    }
  }
}

function shouldDispatchSessionExpired(path, status) {
  return status === 401 && Boolean(accessToken) && path !== "/auth/login" && !sessionExpiredDispatched;
}

function dispatchSessionExpired() {
  if (typeof window === "undefined") return;
  sessionExpiredDispatched = true;
  setAccessToken("");
  window.dispatchEvent(new CustomEvent(AUTH_SESSION_EXPIRED_EVENT));
}

async function request(path, options = {}) {
  const headers = {
    ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    ...(options.headers || {}),
  };
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let message = `Request failed: ${response.status}`;
    try {
      const payload = await response.json();
      if (payload?.detail) {
        message = typeof payload.detail === "string" ? payload.detail : JSON.stringify(payload.detail);
      }
    } catch {
      // Keep the generic status message when the server does not return JSON.
    }
    const error = new Error(message);
    error.status = response.status;
    if (shouldDispatchSessionExpired(path, response.status)) {
      error.isAuthExpired = true;
      dispatchSessionExpired();
    }
    throw error;
  }

  if (response.status === 204) {
    return null;
  }

  return response.json();
}

async function requestBlob(path) {
  const headers = accessToken ? { Authorization: `Bearer ${accessToken}` } : {};
  const response = await fetch(`${API_BASE}${path}`, { headers });
  if (!response.ok) {
    let message = `Request failed: ${response.status}`;
    try {
      const payload = await response.json();
      if (payload?.detail) message = String(payload.detail);
    } catch {
      // Keep the generic status message when the server does not return JSON.
    }
    const error = new Error(message);
    error.status = response.status;
    if (shouldDispatchSessionExpired(path, response.status)) {
      error.isAuthExpired = true;
      dispatchSessionExpired();
    }
    throw error;
  }
  return response.blob();
}

export const apiClient = {
  get: (path) => request(path),
  getBlob: (path) => requestBlob(path),
  post: (path, body) =>
    request(path, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  patch: (path, body) =>
    request(path, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  put: (path, body) =>
    request(path, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  delete: (path) =>
    request(path, {
      method: "DELETE",
    }),
};
