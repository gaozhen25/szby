#!/usr/bin/env node
/**
 * Web 产物冒烟测试：用本机 Chrome 逐个路由跑一遍，收集控制台报错、未捕获异常、
 * 加载失败的请求，并检查 #root 是否真的渲染出了内容。
 *
 * 主要用来卡住「发版后某个页面点进去整页崩溃」这类问题——
 * 页面崩溃时 ErrorBoundary 会接住，#root 里只剩错误界面，同时 pageerror 会有记录。
 *
 * 用法：
 *   node scripts/serve-dist.js dist 4173 &
 *   node scripts/smoke-web.js http://127.0.0.1:4173 / /login /register /annotators
 */
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const os = require('os');

const CHROME =
  process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const PORT = 9333;
const SETTLE_MS = Number(process.env.SMOKE_SETTLE_MS || 6000);
/** 设为 390 等窄宽度可验证手机端页面；留空用默认桌面视口 */
const VIEWPORT_WIDTH = Number(process.env.SMOKE_WIDTH || 0);

const base = process.argv[2] || 'http://127.0.0.1:4173';
const routes = process.argv.slice(3);
if (!routes.length) routes.push('/');

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function httpJson(url) {
  const res = await fetch(url);
  return res.json();
}

class Cdp {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    this.handlers = [];
    ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id != null && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
        return;
      }
      for (const h of this.handlers) h(msg);
    });
  }
  static async connect(wsUrl) {
    const ws = new WebSocket(wsUrl);
    await new Promise((resolve, reject) => {
      ws.addEventListener('open', resolve, { once: true });
      ws.addEventListener('error', reject, { once: true });
    });
    return new Cdp(ws);
  }
  send(method, params = {}) {
    const id = ++this.id;
    this.ws.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }));
  }
  on(fn) {
    this.handlers.push(fn);
  }
}

(async () => {
  const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'qh-smoke-'));
  const chrome = spawn(
    CHROME,
    [
      '--headless=new',
      '--disable-gpu',
      '--no-first-run',
      '--no-default-browser-check',
      `--remote-debugging-port=${PORT}`,
      `--user-data-dir=${userDataDir}`,
      'about:blank',
    ],
    { stdio: 'ignore' },
  );

  let version = null;
  for (let i = 0; i < 50 && !version; i++) {
    await sleep(200);
    try {
      version = await httpJson(`http://127.0.0.1:${PORT}/json/version`);
    } catch {
      /* 还没起来 */
    }
  }
  if (!version) {
    chrome.kill();
    console.error('无法连上 Chrome 调试端口');
    process.exit(1);
  }

  const results = [];
  for (const route of routes) {
    const target = await httpJson(`http://127.0.0.1:${PORT}/json/new?about:blank`).catch(
      async () => {
        // 新版 Chrome 的 /json/new 要求 PUT
        const res = await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, {
          method: 'PUT',
        });
        return res.json();
      },
    );
    const cdp = await Cdp.connect(target.webSocketDebuggerUrl);
    const consoleErrors = [];
    const pageErrors = [];
    const failedRequests = [];

    cdp.on((msg) => {
      if (msg.method === 'Runtime.exceptionThrown') {
        const d = msg.params?.exceptionDetails;
        pageErrors.push(d?.exception?.description || d?.text || 'unknown');
      } else if (msg.method === 'Runtime.consoleAPICalled' && msg.params?.type === 'error') {
        consoleErrors.push(
          (msg.params.args || []).map((a) => a.value ?? a.description ?? '').join(' '),
        );
      } else if (msg.method === 'Network.loadingFailed') {
        failedRequests.push(`${msg.params?.type} ${msg.params?.errorText}`);
      }
    });

    await cdp.send('Runtime.enable');
    await cdp.send('Network.enable');
    await cdp.send('Page.enable');
    if (VIEWPORT_WIDTH) {
      // 窄屏时 webRoute / webComponent 会切到手机端实现（另一批 import() chunk），
      // 这条路径也要覆盖
      await cdp.send('Emulation.setDeviceMetricsOverride', {
        width: VIEWPORT_WIDTH,
        height: 844,
        deviceScaleFactor: 2,
        mobile: VIEWPORT_WIDTH < 768,
      });
    }
    await cdp.send('Page.navigate', { url: base + route });
    await sleep(SETTLE_MS);

    const rootLen = await cdp.send('Runtime.evaluate', {
      expression: 'document.getElementById("root")?.innerHTML.length ?? -1',
      returnByValue: true,
    });
    const bodyText = await cdp.send('Runtime.evaluate', {
      expression: 'document.body.innerText.slice(0,300)',
      returnByValue: true,
    });

    results.push({
      route,
      rootLen: rootLen.result.value,
      pageErrors,
      consoleErrors,
      failedRequests: failedRequests.filter((f) => !/net::ERR_ABORTED/.test(f)),
      text: (bodyText.result.value || '').replace(/\s+/g, ' ').trim(),
    });
    cdp.ws.close();
    await fetch(`http://127.0.0.1:${PORT}/json/close/${target.id}`).catch(() => {});
  }

  chrome.kill();

  let bad = 0;
  for (const r of results) {
    const ok = r.rootLen > 200 && r.pageErrors.length === 0;
    if (!ok) bad++;
    console.log(`\n${ok ? 'PASS' : 'FAIL'}  ${r.route}   #root=${r.rootLen}B`);
    if (r.text) console.log(`      文案: ${r.text.slice(0, 120)}`);
    for (const e of r.pageErrors) console.log(`      未捕获异常: ${e.split('\n')[0]}`);
    for (const e of r.consoleErrors.slice(0, 5)) console.log(`      console.error: ${e.slice(0, 160)}`);
    for (const e of r.failedRequests.slice(0, 5)) console.log(`      请求失败: ${e}`);
  }
  console.log(`\n合计 ${results.length} 个路由，失败 ${bad} 个`);
  process.exit(bad ? 1 : 0);
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
