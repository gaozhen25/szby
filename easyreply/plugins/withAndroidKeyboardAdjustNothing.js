/**
 * 聊天页键盘：adjustNothing + JS 侧 paddingBottom（仅压缩 NavBar 下方区域）。
 * 避免 adjustPan 把导航栏一起顶出屏幕；比 adjustResize 与 WebView 混用更可控。
 */
const { withAndroidManifest, AndroidConfig } = require('@expo/config-plugins');

function withAndroidKeyboardAdjustNothing(config) {
  return withAndroidManifest(config, (cfg) => {
    const manifest = cfg.modResults;
    const mainActivity = AndroidConfig.Manifest.getMainActivityOrThrow(manifest);
    mainActivity.$['android:windowSoftInputMode'] = 'adjustNothing';
    return cfg;
  });
}

module.exports = withAndroidKeyboardAdjustNothing;
