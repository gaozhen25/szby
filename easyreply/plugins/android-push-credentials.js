/**
 * Android 厂商推送凭证 — 自动同步（prebuild / run:android 共用）
 *
 * - 始终同步 libs.versions.toml（华为 AGConnect 需要 `libs` catalog）
 * - 有凭证则复制 agconnect-services.json / google-services.json
 * - 无 google-services.json 时仅移除 FCM，不影响华为及其他厂商通道
 */
const fs = require('fs');
const path = require('path');

const TAG = '[android-push-credentials]';

function credentialsDir(projectRoot) {
  return path.join(projectRoot, 'credentials');
}

function hasCredential(projectRoot, filename) {
  return fs.existsSync(path.join(credentialsDir(projectRoot), filename));
}

/** prebuild 时决定 mx-jpush-expo 是否注入 FCM */
function isFcmEnabledForConfig(projectRoot) {
  return hasCredential(projectRoot, 'google-services.json');
}

function copyFileIfExists(src, dest) {
  if (!fs.existsSync(src)) return false;
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.copyFileSync(src, dest);
  return true;
}

function stripFcmFromAppGradle(contents) {
  let next = contents;

  next = next.replace(/\napply plugin: 'com\.google\.gms\.google-services'/g, '');

  next = next.replace(
    /\n    \/\/ FCM 厂商\n    implementation 'com\.google\.firebase:firebase-messaging:[^']+'\n    implementation 'cn\.jiguang\.sdk\.plugin:fcm:[^']+'/g,
    '',
  );

  return next;
}

function patchAppBuildGradle(appGradlePath, enableFcm) {
  if (!fs.existsSync(appGradlePath)) return;

  const before = fs.readFileSync(appGradlePath, 'utf8');
  const after = enableFcm ? before : stripFcmFromAppGradle(before);

  if (after !== before) {
    fs.writeFileSync(appGradlePath, after);
    console.log(`${TAG} FCM stripped from app/build.gradle (no google-services.json)`);
  }
}

/**
 * @param {string} projectRoot 项目根目录
 * @returns {{ fcmEnabled: boolean; huaweiConfigured: boolean }}
 */
function syncAndroidPushCredentials(projectRoot) {
  const androidRoot = path.join(projectRoot, 'android');
  const credDir = credentialsDir(projectRoot);

  // ---- libs version catalog（华为 AGConnect 必需）----
  const rnToml = path.join(projectRoot, 'node_modules', 'react-native', 'gradle', 'libs.versions.toml');
  const destToml = path.join(androidRoot, 'gradle', 'libs.versions.toml');

  if (copyFileIfExists(rnToml, destToml)) {
    console.log(`${TAG} synced libs.versions.toml`);
  } else if (fs.existsSync(androidRoot)) {
    console.warn(`${TAG} missing ${rnToml}`);
  }

  if (!fs.existsSync(androidRoot)) {
    return {
      fcmEnabled: hasCredential(projectRoot, 'google-services.json'),
      huaweiConfigured: hasCredential(projectRoot, 'agconnect-services.json'),
    };
  }

  const appGradlePath = path.join(androidRoot, 'app', 'build.gradle');

  // ---- 华为（始终尝试复制，不修改 Gradle 华为依赖）----
  const agcCopied = copyFileIfExists(
    path.join(credDir, 'agconnect-services.json'),
    path.join(androidRoot, 'app', 'agconnect-services.json'),
  );
  if (agcCopied) {
    console.log(`${TAG} synced agconnect-services.json`);
  } else {
    console.warn(`${TAG} agconnect-services.json not in credentials/ (Huawei channel needs it at runtime)`);
  }

  // ---- FCM：有凭证才启用，否则从 Gradle 移除 ----
  const fcmCopied = copyFileIfExists(
    path.join(credDir, 'google-services.json'),
    path.join(androidRoot, 'app', 'google-services.json'),
  );

  if (fcmCopied) {
    console.log(`${TAG} synced google-services.json — FCM enabled`);
  } else {
    console.log(`${TAG} no google-services.json — FCM disabled for this build`);
    patchAppBuildGradle(appGradlePath, false);
  }

  return {
    fcmEnabled: fcmCopied,
    huaweiConfigured: agcCopied,
  };
}

module.exports = {
  TAG,
  credentialsDir,
  hasCredential,
  isFcmEnabledForConfig,
  syncAndroidPushCredentials,
};
