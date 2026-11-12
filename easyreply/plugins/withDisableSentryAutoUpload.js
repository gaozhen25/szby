/**
 * Expo Config Plugin：Sentry 未配置上传凭证时，禁用 iOS 构建期 source map 自动上传。
 *
 * 背景（重要）：
 *   Sentry 注入的 "Bundle React Native code and images" 脚本，实际执行的是
 *   `sentry-cli react-native xcode … react-native-xcode.sh`。
 *   当缺少 org / project / authToken 时，sentry-cli 会先报错退出；而 .env 里设置了
 *   SENTRY_ALLOW_FAILURE=true 会让它以 exit 0「假装成功」，于是真正负责打包的
 *   react-native-xcode.sh 根本没机会执行：
 *     - Release：不生成 main.jsbundle  → App 启动直接崩溃
 *     - Debug  ：不写 ip.txt           → 真机找不到 Metro，报 "No script URL provided"
 *
 *   设置 SENTRY_DISABLE_AUTO_UPLOAD=true 后，sentry-xcode.sh 会跳过 sentry-cli，
 *   直接执行 react-native-xcode.sh，打包恢复正常。
 *
 * 写入位置：ios/.xcode.env（Xcode 构建脚本与 expo run:ios 都会 source 它），
 *           每次 `expo prebuild --clean` 重建 ios 目录后由本插件自动重新注入。
 *
 * 当配置了真实的 SENTRY_AUTH_TOKEN 时，本插件不做任何处理（保留正常上传行为）。
 */
const fs = require('fs');
const path = require('path');
const { withDangerousMod } = require('@expo/config-plugins');

const ENV_LINE = 'export SENTRY_DISABLE_AUTO_UPLOAD=true';

function withDisableSentryAutoUpload(config) {
  const hasAuthToken = Boolean((process.env.SENTRY_AUTH_TOKEN ?? '').trim());
  if (hasAuthToken) {
    return config;
  }

  return withDangerousMod(config, [
    'ios',
    (cfg) => {
      const xcodeEnvPath = path.join(cfg.modRequest.platformProjectRoot, '.xcode.env');

      let contents = '';
      try {
        contents = fs.readFileSync(xcodeEnvPath, 'utf8');
      } catch {
        contents = '';
      }

      if (!contents.includes('SENTRY_DISABLE_AUTO_UPLOAD')) {
        const needsNewline = contents.length > 0 && !contents.endsWith('\n');
        contents +=
          `${needsNewline ? '\n' : ''}\n` +
          '# 由 withDisableSentryAutoUpload 注入：\n' +
          '# Sentry 未配置上传凭证时跳过 source map 上传，避免打包脚本被 sentry-cli 中断\n' +
          `${ENV_LINE}\n`;
        fs.writeFileSync(xcodeEnvPath, contents);
        console.log('[withDisableSentryAutoUpload] 已在 ios/.xcode.env 注入 SENTRY_DISABLE_AUTO_UPLOAD=true');
      }

      return cfg;
    },
  ]);
}

module.exports = withDisableSentryAutoUpload;
