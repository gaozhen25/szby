import type { ExpoConfig } from 'expo/config';

// eslint-disable-next-line @typescript-eslint/no-require-imports
const { isFcmEnabledForConfig } = require('./plugins/android-push-credentials');

// ============================================================
// 轻回 App 统一配置
// ============================================================

const APP_ENV =
  process.env.EXPO_PUBLIC_APP_ENV?.trim() ||
  process.env.APP_ENV?.trim() ||
  'production';
const isTest = APP_ENV === 'test';
const isProduction = APP_ENV === 'production';
/** 测试/开发环境 API 可能为 http：Android 明文流量 / iOS ATS 均需显式放行 */
const allowCleartextHttp = !isProduction;

const API_HOST = (
  (isTest
    ? process.env.EXPO_PUBLIC_API_HOST_TEST ?? process.env.EXPO_PUBLIC_API_HOST
    : isProduction
      ? process.env.EXPO_PUBLIC_API_HOST_PROD
      : process.env.EXPO_PUBLIC_API_HOST) ?? ''
).trim();

const APP_NAME = isTest ? '轻回测试' : '轻回';
const APP_SLUG = 'qinghui';
const APP_SCHEME = 'qinghui';
/** 发版前在此手动修改版本号，勿通过环境变量或命令行注入 */
const APP_VERSION = '1.1.5';

/** 各环境 Bundle ID */
const BUNDLE_ID = isTest ? 'com.cheeliu.qinghui.test' : 'com.cheeliu.qinghui';

/** Sentry 服务地址 / 项目（source map 上传需要 org + project slug） */
const SENTRY_URL = (process.env.SENTRY_URL as string) || 'https://sentry.io/';
const SENTRY_ORG = (process.env.SENTRY_ORG as string)?.trim() || '';
const SENTRY_PROJECT = (process.env.SENTRY_PROJECT as string)?.trim() || '';

/** 极光/厂商通道占位值：未配置环境变量时暂用，后续替换为正式值 */
function jpushPlaceholder(v: string | undefined, name: string): string {
  const trimmed = v?.trim();
  return trimmed || `placeholder_jpush_${name}`;
}

const JPUSH_APP_KEY = jpushPlaceholder(
  process.env.JPUSH_APP_KEY ?? process.env.EXPO_PUBLIC_JPUSH_APP_KEY,
  'app_key',
);

const JPUSH_CHANNEL =
  process.env.EXPO_PUBLIC_JPUSH_CHANNEL?.trim() ||
  process.env.JPUSH_CHANNEL?.trim() ||
  'developer-default';

const JPUSH_XIAOMI_APP_ID = jpushPlaceholder(process.env.JPUSH_XIAOMI_APP_ID, 'xiaomi_app_id');
const JPUSH_XIAOMI_APP_KEY = jpushPlaceholder(process.env.JPUSH_XIAOMI_APP_KEY, 'xiaomi_app_key');
const JPUSH_VIVO_APP_ID = jpushPlaceholder(process.env.JPUSH_VIVO_APP_ID, 'vivo_app_id');
const JPUSH_VIVO_APP_KEY = jpushPlaceholder(process.env.JPUSH_VIVO_APP_KEY, 'vivo_app_key');
const JPUSH_HONOR_APP_ID = jpushPlaceholder(process.env.JPUSH_HONOR_APP_ID, 'honor_app_id');

const isJPushProduction = APP_ENV === 'production';

/** 有 credentials/google-services.json 时自动启用 FCM，否则跳过（华为通道不受影响） */
const isFcmEnabled = isFcmEnabledForConfig(process.cwd());

const APP_ICON = './assets/images/icon-qinghui.png';

const config: ExpoConfig = {
  name: APP_NAME,
  slug: APP_SLUG,
  version: APP_VERSION,
  orientation: 'portrait',
  icon: APP_ICON,
  scheme: APP_SCHEME,
  userInterfaceStyle: 'automatic',

  // 声明中文本地化：系统相机/相册控件（Cancel、Use Photo 等）才会随中文显示
  locales: {
    'zh-Hans': './locales/zh-Hans.json',
  },

  // ---------- iOS ----------
  ios: {
    supportsTablet: true,
    bundleIdentifier: BUNDLE_ID,
    infoPlist: {
      CFBundleDevelopmentRegion: 'zh-Hans',
      CFBundleAllowMixedLocalizations: true,
      CFBundleLocalizations: ['zh-Hans', 'en'],
      NSMicrophoneUsageDescription: '允许使用麦克风以发送语音消息',
      NSPhotoLibraryAddUsageDescription: '允许保存聊天中的图片和视频到相册',
      // 测试包 API 为 http://...，需关闭 ATS 明文限制；生产包保持默认（仅 https）
      ...(allowCleartextHttp
        ? {
            NSAppTransportSecurity: {
              NSAllowsArbitraryLoads: true,
            },
          }
        : {}),
    },
  },

  // ---------- Android ----------
  android: {
    package: BUNDLE_ID,
    // 键盘模式由 plugins/withAndroidKeyboardAdjustNothing 设为 adjustNothing；
    // JS 侧 paddingBottom 垫高输入区，导航栏保持固定。
    adaptiveIcon: {
      backgroundColor: '#E6F4FE',
      foregroundImage: APP_ICON,
    },
    permissions: [
      'VIBRATE',
      'NOTIFICATIONS',
      'POST_NOTIFICATIONS',
      'RECORD_AUDIO',
      'MODIFY_AUDIO_SETTINGS',
      'READ_MEDIA_IMAGES',
      'READ_MEDIA_VIDEO',
    ],
  },

  // ---------- Web ----------
  web: {
    bundler: 'metro',
    // single：标准 SPA，兼容 expo start --web；配合 nginx try_files 部署
    output: 'single',
    favicon: './assets/images/favicon.png',
  },

  // ---------- 插件 ----------
  plugins: [
    [
      'expo-router',
      {
        // Web 不按路由拆 chunk：实测拆完首屏 JS 只从 2124KB 降到 2084KB（gzip，-1.9%），
        // 因为 antd/RN-web/chatMessage 被多个路由共用，最终都会被提到首屏同步加载的
        // __common 里；省下的那点体积换来的是 55 个 chunk、"路由壳 → 页面" 二级瀑布，
        // 以及发版后异步 chunk 加载失败导致的整页崩溃。
        // 首屏体积靠「不引 barrel」来降（见 src/ui/web/antd-icons.ts），
        // 真正需要延迟的重模块仍由 webRoute / webComponent 显式 import() 控制。
        asyncRoutes: {
          web: false,
          default: 'development',
        },
      },
    ],
    [
      'expo-build-properties',
      {
        ios: {
          deploymentTarget: '15.1',
        },
        android: {
          usesCleartextTraffic: allowCleartextHttp,
        },
      },
    ],
    [
      'expo-image-picker',
      {
        photosPermission: '允许访问相册以发送图片消息',
        cameraPermission: '允许使用相机以拍摄并发送图片消息',
      },
    ],
    [
      'expo-audio',
      {
        microphonePermission: '允许使用麦克风以发送语音消息',
        recordAudioAndroid: true,
        enableBackgroundPlayback: false,
        enableBackgroundRecording: false,
      },
    ],
    'expo-video',
    'expo-sharing',
    [
      'expo-media-library',
      {
        photosPermission: '允许访问系统相册以预览和保存聊天图片或视频',
        savePhotosPermission: '允许保存聊天中的图片和视频到相册',
      },
    ],
    'expo-image',
    'expo-sqlite',
    [
      'expo-splash-screen',
      {
        image: APP_ICON,
        resizeMode: 'contain',
        backgroundColor: '#ffffff',
      },
    ],
    [
      '@sentry/react-native',
      {
        url: SENTRY_URL,
        ...(SENTRY_ORG ? { organization: SENTRY_ORG } : {}),
        ...(SENTRY_PROJECT ? { project: SENTRY_PROJECT } : {}),
      },
    ],
    [
      'expo-notifications',
      {
        icon: APP_ICON,
        color: '#4A90D9',
        defaultChannel: 'default',
        sounds: ['./assets/new_msg.wav'],
      },
    ],
    [
      'mx-jpush-expo',
      {
        appKey: JPUSH_APP_KEY,
        channel: JPUSH_CHANNEL,
        packageName: BUNDLE_ID,
        apsForProduction: isJPushProduction,
        vendorChannels: {
          huawei: { enabled: true },
          fcm: { enabled: isFcmEnabled },
          xiaomi: {
            appId: JPUSH_XIAOMI_APP_ID,
            appKey: JPUSH_XIAOMI_APP_KEY,
          },
          vivo: {
            appId: JPUSH_VIVO_APP_ID,
            appKey: JPUSH_VIVO_APP_KEY,
          },
          honor: {
            appId: JPUSH_HONOR_APP_ID,
          },
        },
      },
    ],
    './plugins/withAndroidVendorPush',
    './plugins/withAndroidMavenMirrors',
    './plugins/withDisableSentryAutoUpload',
    './plugins/withSentryCocoaPodsFallback',
    './plugins/withIosMetroBundleURLFallback',
    './plugins/withAndroidDebugMetro',
    './plugins/withAndroidKeyboardAdjustNothing',
  ],

  experiments: {
    typedRoutes: true,
  },

  extra: {
    router: {
      root: 'src/app',
    },
    appName: APP_NAME,
    appVersion: APP_VERSION,
    env: APP_ENV,
    apiHost: API_HOST,
    sentryUrl: SENTRY_URL,
    jpushConfigured: Boolean(JPUSH_APP_KEY),
    eas: {
      projectId: process.env.EXPO_PUBLIC_EAS_PROJECT_ID || '',
    },
  },
};

export default config;

export { APP_ENV, APP_NAME, APP_VERSION };
