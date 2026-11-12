#!/usr/bin/env node
/**
 * 真机 Debug：把手机上的 127.0.0.1:8099 转到电脑 Metro，不必走局域网。
 */
const { execSync } = require('child_process');

const PORT = 8099;

function sh(cmd) {
  try {
    return execSync(cmd, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
  } catch {
    return '';
  }
}

const ids = sh('adb devices')
  .split('\n')
  .map((line) => line.trim())
  .filter((line) => /\sdevice$/.test(line))
  .map((line) => line.split(/\s+/)[0])
  .filter(Boolean);

if (ids.length === 0) {
  console.warn(`[adb-reverse-metro] 未检测到设备，跳过 tcp:${PORT}`);
  process.exit(0);
}

for (const id of ids) {
  try {
    execSync(`adb -s ${id} reverse tcp:${PORT} tcp:${PORT}`, { stdio: 'inherit' });
    console.log(`[adb-reverse-metro] ${id} → 127.0.0.1:${PORT}`);
  } catch (e) {
    console.warn(`[adb-reverse-metro] ${id} reverse 失败`, e instanceof Error ? e.message : e);
  }
}
