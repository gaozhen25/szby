#!/usr/bin/env node
/**
 * dist/index.html 后处理：
 *   1. 注入首屏 loading 样式（#root 还空着时显示转圈，避免白屏）
 *   2. 给首屏同步 JS 加 preload。注意必须和 <script> 的请求模式一致：
 *      页面里的 <script src=... defer> 是 no-cors 请求，preload 若带 crossorigin
 *      就变成 anonymous CORS 请求，两者缓存键不同 → 同一个文件会被下载两次。
 *   3. 写 build-info.json，供前端做「发版了没」判定（见 src/lib/web-build-version.ts）
 *
 * 用法：node scripts/postbuild-web-html.js <distDir>
 */
const fs = require('fs');
const path = require('path');

const dist = process.argv[2] || 'dist';
const indexPath = path.join(dist, 'index.html');

let html = fs.readFileSync(indexPath, 'utf8');

const BOOT_STYLE =
  '<style id="qh-boot">#root:empty{min-height:100vh;display:flex;align-items:center;justify-content:center;background:#F5F6F8}' +
  '#root:empty::after{content:"";width:28px;height:28px;border:3px solid #E6EDFB;border-top-color:#5AB2AC;border-radius:50%;animation:qh-spin .8s linear infinite}' +
  '@keyframes qh-spin{to{transform:rotate(360deg)}}</style>';

if (!html.includes('id="qh-boot"')) {
  html = html.replace('</head>', BOOT_STYLE + '</head>');
}

/** 收集 body 里首屏同步加载的 JS（runtime / __common / entry），按出现顺序 */
const syncScripts = [...html.matchAll(/<script src="(\/_expo\/static\/js\/web\/[^"]+\.js)"\s+defer><\/script>/g)].map(
  (m) => m[1],
);

// 旧版本注入过带 crossorigin 的 preload，会导致 entry 被下载两次，这里先清掉
html = html.replace(/<link rel="preload" as="script"[^>]*>/g, '');

if (syncScripts.length) {
  const links = syncScripts
    .map((src) => `<link rel="preload" as="script" href="${src}">`)
    .join('');
  html = html.replace('</head>', links + '</head>');
}

fs.writeFileSync(indexPath, html);
console.log(
  `[postbuild-web] index.html: boot loading + ${syncScripts.length} 个首屏 JS preload（无 crossorigin，与 <script> 请求模式一致）`,
);

const entry = syncScripts.find((s) => s.includes('/entry-')) ?? null;
fs.writeFileSync(
  path.join(dist, 'build-info.json'),
  JSON.stringify({ builtAt: new Date().toISOString(), entry }, null, 2) + '\n',
);
console.log('[postbuild-web] wrote build-info.json');
