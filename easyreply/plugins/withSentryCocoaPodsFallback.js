/**
 * Expo Config Plugin：避免 RNSentry 在 pod install 时从 GitHub 下载 Sentry.xcframework。
 *
 * 国内网络访问 github.com 常超时（Net::OpenTimeout），导致 prebuild / pod install 失败。
 * 设置 SENTRY_USE_XCFRAMEWORK=0 后改走 CocoaPods 的 Sentry 依赖。
 *
 * 每次 `expo prebuild --clean` 会重建 Podfile，由本插件重新注入。
 */
const { withDangerousMod } = require('@expo/config-plugins');
const fs = require('fs');
const path = require('path');

const MARKER = 'SENTRY_USE_XCFRAMEWORK';
const INJECT = [
  '# 由 withSentryCocoaPodsFallback 注入：跳过 GitHub xcframework 直链，改用 CocoaPods Sentry',
  "ENV['SENTRY_USE_XCFRAMEWORK'] ||= '0'",
  '',
].join('\n');

function withSentryCocoaPodsFallback(config) {
  return withDangerousMod(config, [
    'ios',
    (cfg) => {
      const podfilePath = path.join(cfg.modRequest.platformProjectRoot, 'Podfile');
      let contents = '';
      try {
        contents = fs.readFileSync(podfilePath, 'utf8');
      } catch {
        return cfg;
      }

      if (contents.includes(MARKER)) {
        return cfg;
      }

      fs.writeFileSync(podfilePath, `${INJECT}${contents}`);
      console.log('[withSentryCocoaPodsFallback] 已在 ios/Podfile 注入 SENTRY_USE_XCFRAMEWORK=0');
      return cfg;
    },
  ]);
}

module.exports = withSentryCocoaPodsFallback;
