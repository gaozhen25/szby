#!/usr/bin/env node
/** run:android 前自动同步凭证（不经过 prebuild 时也生效） */
const path = require('path');
const { syncAndroidPushCredentials } = require('../plugins/android-push-credentials');

const projectRoot = path.resolve(__dirname, '..');
syncAndroidPushCredentials(projectRoot);
