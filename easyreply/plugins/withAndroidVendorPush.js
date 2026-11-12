/**
 * Expo Config Plugin：prebuild 后自动同步厂商推送凭证
 * 必须放在 mx-jpush-expo 之后
 */
const { withDangerousMod } = require('@expo/config-plugins');
const { syncAndroidPushCredentials } = require('./android-push-credentials');

function withAndroidVendorPush(config) {
  return withDangerousMod(config, [
    'android',
    async (cfg) => {
      syncAndroidPushCredentials(cfg.modRequest.projectRoot);
      return cfg;
    },
  ]);
}

module.exports = withAndroidVendorPush;
