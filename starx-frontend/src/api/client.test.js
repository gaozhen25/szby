import assert from "node:assert/strict";
import test from "node:test";

function createLocalStorage() {
  const store = new Map();
  return {
    getItem: (key) => store.get(key) || null,
    setItem: (key, value) => store.set(key, String(value)),
    removeItem: (key) => store.delete(key),
  };
}

async function loadClient() {
  return import(`./client.js?test=${Date.now()}-${Math.random()}`);
}

test("expired authenticated requests clear token and notify the app once", async () => {
  const listeners = new Map();
  globalThis.CustomEvent = class CustomEvent {
    constructor(type) {
      this.type = type;
    }
  };
  globalThis.window = {
    localStorage: createLocalStorage(),
    addEventListener: (type, listener) => listeners.set(type, listener),
    removeEventListener: (type) => listeners.delete(type),
    dispatchEvent: (event) => listeners.get(event.type)?.(event),
  };

  const { AUTH_SESSION_EXPIRED_EVENT, apiClient, setAccessToken } = await loadClient();
  let expiredCount = 0;
  window.addEventListener(AUTH_SESSION_EXPIRED_EVENT, () => {
    expiredCount += 1;
  });
  setAccessToken("expired-token");

  globalThis.fetch = async () => ({
    ok: false,
    status: 401,
    json: async () => ({ detail: "Not authenticated" }),
  });

  await assert.rejects(() => apiClient.get("/auth/me"), {
    status: 401,
    isAuthExpired: true,
  });
  await assert.rejects(() => apiClient.get("/accounts"), {
    status: 401,
  });

  assert.equal(window.localStorage.getItem("starx_token"), null);
  assert.equal(expiredCount, 1);
});

test("login failures do not dispatch session-expired events", async () => {
  const events = [];
  globalThis.CustomEvent = class CustomEvent {
    constructor(type) {
      this.type = type;
    }
  };
  globalThis.window = {
    localStorage: createLocalStorage(),
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: (event) => events.push(event.type),
  };
  globalThis.fetch = async () => ({
    ok: false,
    status: 401,
    json: async () => ({ detail: "用户名或密码错误" }),
  });

  const { apiClient, setAccessToken } = await loadClient();
  setAccessToken("stale-token");

  await assert.rejects(() => apiClient.post("/auth/login", { email: "a@test.com", password: "bad" }), {
    status: 401,
  });

  assert.deepEqual(events, []);
  assert.equal(window.localStorage.getItem("starx_token"), "stale-token");
});
