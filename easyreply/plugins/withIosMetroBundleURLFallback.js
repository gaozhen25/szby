/**
 * Expo Config Plugin：Debug 下 Metro 探测失败时回退到 127.0.0.1:8081，
 * 避免 iOS 模拟器出现 "No script URL provided / unsanitizedScriptURLString = (null)"。
 *
 * 原因简述：
 * - Debug 默认 SKIP_BUNDLING，不嵌入 main.jsbundle
 * - RCTBundleURLProvider 若探测不到 packager，会返回 nil
 * - 模拟器应直连本机 Metro
 */
const { withAppDelegate } = require('@expo/config-plugins');

const FALLBACK_BLOCK = `
  override func bundleURL() -> URL? {
#if DEBUG
    let provider = RCTBundleURLProvider.sharedSettings()
#if targetEnvironment(simulator)
    // 模拟器：始终走本机 Metro，避免残留 jsLocation / LAN 探测失败
    provider.jsLocation = "127.0.0.1:8081"
#endif
    if let url = provider.jsBundleURL(forBundleRoot: ".expo/.virtual-metro-entry") {
      return url
    }
    return URL(string: "http://127.0.0.1:8081/.expo/.virtual-metro-entry.bundle?platform=ios&dev=true&minify=false&modulesOnly=false&runModule=true")
#else
    return Bundle.main.url(forResource: "main", withExtension: "jsbundle")
#endif
  }
`.trim();

function withIosMetroBundleURLFallback(config) {
  return withAppDelegate(config, (cfg) => {
    if (cfg.modResults.language !== 'swift') {
      return cfg;
    }

    let contents = cfg.modResults.contents;

    // 已注入则跳过
    if (contents.includes('127.0.0.1:8081/.expo/.virtual-metro-entry.bundle')) {
      return cfg;
    }

    const pattern =
      /override func bundleURL\(\) -> URL\? \{[\s\S]*?\n  \}/m;

    if (!pattern.test(contents)) {
      console.warn(
        '[withIosMetroBundleURLFallback] 未找到 bundleURL()，跳过注入',
      );
      return cfg;
    }

    contents = contents.replace(pattern, FALLBACK_BLOCK);
    cfg.modResults.contents = contents;
    console.log('[withIosMetroBundleURLFallback] 已注入 Debug Metro localhost 回退');
    return cfg;
  });
}

module.exports = withIosMetroBundleURLFallback;
