#!/usr/bin/env node
/**
 * 本地验证 dist 的最小静态服务器，行为对齐 nginx.conf：
 *   - SPA 回退到 index.html
 *   - index.html / build-info.json 不缓存，_expo/static 长缓存
 *   - 优先返回预压缩的 .gz（等价 gzip_static on）
 * 用法：node scripts/serve-dist.js [distDir] [port]
 */
const http = require('http');
const fs = require('fs');
const path = require('path');

const dist = path.resolve(process.argv[2] || 'dist');
const port = Number(process.argv[3] || 4173);

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.ico': 'image/x-icon',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.woff2': 'font/woff2',
};

function send(res, status, headers, body) {
  res.writeHead(status, headers);
  res.end(body);
}

const server = http.createServer((req, res) => {
  const urlPath = decodeURIComponent((req.url || '/').split('?')[0]);
  let filePath = path.join(dist, urlPath);

  if (!filePath.startsWith(dist)) return send(res, 403, {}, 'forbidden');
  if (!fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
    // SPA 回退
    filePath = path.join(dist, 'index.html');
  }

  const ext = path.extname(filePath);
  const headers = { 'Content-Type': MIME[ext] || 'application/octet-stream' };

  const isImmutable = urlPath.startsWith('/_expo/static/');
  headers['Cache-Control'] = isImmutable
    ? 'public, max-age=31536000, immutable'
    : 'no-cache, no-store, must-revalidate';

  const acceptsGzip = /\bgzip\b/.test(req.headers['accept-encoding'] || '');
  const gz = filePath + '.gz';
  if (acceptsGzip && fs.existsSync(gz)) {
    headers['Content-Encoding'] = 'gzip';
    headers.Vary = 'Accept-Encoding';
    return send(res, 200, headers, fs.readFileSync(gz));
  }
  return send(res, 200, headers, fs.readFileSync(filePath));
});

server.listen(port, '127.0.0.1', () => {
  console.log(`[serve-dist] http://127.0.0.1:${port}  root=${dist}`);
});
