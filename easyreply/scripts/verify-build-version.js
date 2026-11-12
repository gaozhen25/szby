#!/usr/bin/env node
/**
 * 验证「发版自愈」的版本判定。
 *
 * 这是自愈逻辑里最容易出错的一环：页面里读到的 entry 路径必须和 build-info.json
 * 的 entry 字段格式完全一致，否则 isStaleBuild() 会永远为真，
 * 每次报错都触发刷新（刷新死循环）。
 *
 * 用两步验证：
 *   1. 正常状态：两边取值应当相同，stale=false
 *   2. 模拟发版：临时把 build-info.json 的 entry 改掉，stale 应当变成 true
 *
 * 用法：
 *   node scripts/serve-dist.js dist 4173 &
 *   node scripts/verify-build-version.js http://127.0.0.1:4173 [distDir]
 */
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const CHROME =
  process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const PORT = 9334;
const base = process.argv[2] || 'http://127.0.0.1:4173';
const dist = path.resolve(process.argv[3] || 'dist');
const buildInfoPath = path.join(dist, 'build-info.json');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** 与 src/lib/web-build-version.ts 的取值逻辑保持一致 */
const PROBE = `(async () => {
  const el = document.querySelector('script[src*="/_expo/static/js/web/entry-"]');
  const running = el ? new URL(el.src, location.origin).pathname : null;
  let deployed = null;
  try {
    const res = await fetch('/build-info.json?t=' + Date.now(), { cache: 'no-store', credentials: 'omit' });
    deployed = res.ok ? (await res.json()).entry : null;
  } catch (e) { deployed = 'FETCH_FAILED: ' + e.message; }
  return JSON.stringify({
    running,
    deployed,
    stale: !!running && !!deployed && deployed !== running,
  });
})()`;

async function main() {
  const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'qh-ver-'));
  const chrome = spawn(
    CHROME,
    [
      '--headless=new',
      '--disable-gpu',
      '--no-first-run',
      `--remote-debugging-port=${PORT}`,
      `--user-data-dir=${userDataDir}`,
      'about:blank',
    ],
    { stdio: 'ignore' },
  );

  let target = null;
  for (let i = 0; i < 50 && !target; i++) {
    await sleep(200);
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      target = list.find((t) => t.type === 'page' && t.webSocketDebuggerUrl);
    } catch {
      /* 还没起来 */
    }
  }
  if (!target) throw new Error('无法连上 Chrome 调试端口');

  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => {
    ws.addEventListener('open', res, { once: true });
    ws.addEventListener('error', rej, { once: true });
  });
  let msgId = 0;
  const pending = new Map();
  ws.addEventListener('message', (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) {
      pending.get(m.id)(m.result);
      pending.delete(m.id);
    }
  });
  const send = (method, params = {}) => {
    const id = ++msgId;
    ws.send(JSON.stringify({ id, method, params }));
    return new Promise((r) => pending.set(id, r));
  };

  const probe = async () => {
    const r = await send('Runtime.evaluate', {
      expression: PROBE,
      awaitPromise: true,
      returnByValue: true,
    });
    return JSON.parse(r.result.value);
  };

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Page.navigate', { url: `${base}/login` });
  await sleep(5000);

  const href = await send('Runtime.evaluate', {
    expression: 'location.href',
    returnByValue: true,
  });
  if (!String(href.result.value).startsWith(base)) {
    throw new Error(`导航没生效，当前地址是 ${href.result.value}`);
  }

  let failed = 0;

  const normal = await probe();
  console.log('\n[1] 正常状态');
  console.log(`    页面运行的 entry : ${normal.running}`);
  console.log(`    服务器发布的 entry: ${normal.deployed}`);
  if (normal.running && normal.running === normal.deployed && normal.stale === false) {
    console.log('    PASS 两边一致，不会误触发刷新');
  } else {
    failed++;
    console.log('    FAIL 两边取值不一致 —— 会导致每次报错都刷新');
  }

  const original = fs.readFileSync(buildInfoPath, 'utf8');
  try {
    fs.writeFileSync(
      buildInfoPath,
      JSON.stringify(
        { builtAt: new Date().toISOString(), entry: '/_expo/static/js/web/entry-FAKENEWBUILD.js' },
        null,
        2,
      ),
    );
    const stale = await probe();
    console.log('\n[2] 模拟发版（改掉 build-info.json 的 entry）');
    console.log(`    服务器发布的 entry: ${stale.deployed}`);
    if (stale.stale === true) {
      console.log('    PASS 能识别出发版，会触发一次自愈刷新');
    } else {
      failed++;
      console.log('    FAIL 识别不出发版 —— 自愈不会生效');
    }
  } finally {
    fs.writeFileSync(buildInfoPath, original);
  }

  chrome.kill();
  console.log(`\n${failed ? `失败 ${failed} 项` : '全部通过'}`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
