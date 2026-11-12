/**
 * Debug 真机通过 USB（adb reverse）拉 Metro，不依赖局域网 IP。
 * 端口 8099，避开 Web / 其它项目常用的 8081、8082。
 *
 * 同时为 debug 变体打开明文 HTTP：Debug 包要拉 Metro，测试环境 API 也可能是 http。
 */
const fs = require('fs');
const path = require('path');
const { withMainApplication, withDangerousMod } = require('@expo/config-plugins');

const METRO_PORT = 8099;
const DEBUG_HTTP_HOST = `127.0.0.1:${METRO_PORT}`;

const DEBUG_MANIFEST = `<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    xmlns:tools="http://schemas.android.com/tools">
  <application
      android:usesCleartextTraffic="true"
      tools:targetApi="28"
      tools:replace="android:usesCleartextTraffic" />
</manifest>
`;

function withAndroidDebugMetro(config) {
  config = withMainApplication(config, (cfg) => {
    let src = cfg.modResults.contents;

    if (!src.includes('import android.preference.PreferenceManager')) {
      src = src.replace(
        'import android.app.Application',
        'import android.app.Application\nimport android.preference.PreferenceManager',
      );
    }

    if (src.includes('debug_http_host')) {
      src = src.replace(
        /putString\("debug_http_host",\s*"[^"]+"\)/,
        `putString("debug_http_host", "${DEBUG_HTTP_HOST}")`,
      );
    } else {
      src = src.replace(
        /override fun onCreate\(\) \{\n\s*super\.onCreate\(\)/,
        `override fun onCreate() {\n    super.onCreate()\n    if (BuildConfig.DEBUG) {\n      PreferenceManager.getDefaultSharedPreferences(this)\n        .edit()\n        .putString("debug_http_host", "${DEBUG_HTTP_HOST}")\n        .apply()\n    }`,
      );
    }

    cfg.modResults.contents = src;
    return cfg;
  });

  config = withDangerousMod(config, [
    'android',
    async (cfg) => {
      const debugDir = path.join(cfg.modRequest.platformProjectRoot, 'app/src/debug');
      fs.mkdirSync(debugDir, { recursive: true });
      fs.writeFileSync(path.join(debugDir, 'AndroidManifest.xml'), DEBUG_MANIFEST);
      return cfg;
    },
  ]);

  return config;
}

module.exports = withAndroidDebugMetro;
module.exports.METRO_PORT = METRO_PORT;
