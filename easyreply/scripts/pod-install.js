#!/usr/bin/env node
const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const iosDir = path.resolve(__dirname, '..', 'ios');
if (!fs.existsSync(iosDir)) {
  console.error('[pod:install] ios/ 不存在，请先运行 pnpm run prebuild:test');
  process.exit(1);
}

const result = spawnSync(
  process.execPath,
  [path.join(__dirname, 'with-github-mirror.js'), 'pod', 'install', '--repo-update'],
  {
    stdio: 'inherit',
    cwd: iosDir,
    env: process.env,
  },
);

process.exit(result.status ?? 1);
