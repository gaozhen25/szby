export async function api(path, options = {}) {
  const res = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers: {
      ...(options.body ? { "content-type": "application/json" } : {}),
      ...(options.headers || {}),
    },
  });
  const raw = await res.text();
  let body = {};
  if (raw) {
    try {
      body = JSON.parse(raw);
    } catch {
      body = { detail: raw };
    }
  }
  if (!res.ok) {
    const msg = (body.detail && body.detail.message) || body.detail || "请求失败";
    const error = new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
    error.status = res.status;
    throw error;
  }
  return body;
}
