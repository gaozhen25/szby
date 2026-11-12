# 编码环境

## 1. 运行时与工具链

| 项 | 版本 / 要求 |
|----|------------|
| 操作系统 | macOS（iOS / Android 原生调试） |
| Node.js | **24.14.0**（`package.json` → `volta.node`，推荐用 [Volta](https://volta.sh) 锁定） |
| 包管理 | pnpm + `pnpm-lock.yaml`（勿用 npm install） |
| 框架 | Expo SDK **55**（`expo ~55.0.4`） |
| React | 19.2.0 |
| React Native | 0.83.2 |
| TypeScript | ~5.9.2，`strict: true` |
| ESLint | 9 + `eslint-config-expo ~55.0.0` |

### 原生调试（按需）

| 平台 | 要求 |
|------|------|
| Android | Android SDK，建议在 `~/.zshrc` 配置 `ANDROID_HOME` / `ANDROID_SDK_ROOT` |
| iOS | Xcode + CocoaPods，最低部署版本 **15.1** |

```bash
# Android SDK（写入 ~/.zshrc）
export ANDROID_HOME=$HOME/Library/Android/sdk
export ANDROID_SDK_ROOT=$HOME/Library/Android/sdk
export PATH=$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH
```

---

## 2. 项目初始化

```bash
volta install node@24.14.0   # 或确保 Node 为 24.14.0
# 启用 pnpm（任选其一）：corepack enable && corepack prepare pnpm@9.15.3 --activate
# 或：npm i -g pnpm@9.15.3
pnpm install                  # postinstall 自动执行 patch-package
```

---

## 3. TypeScript 配置（`tsconfig.json`）

- 继承 `expo/tsconfig.base`
- 路径别名：`@/*` → `src/*`，`@/assets/*` → `assets/*`
- 类型文件：`.expo/types/**/*.ts`、`expo-env.d.ts`（Expo 自动生成）

---

## 4. 运行环境变量

本地编码通过 **pnpm script 后缀** 切换环境（`:test` 或 `:prod`），无需改 `app.config.ts` 中的环境逻辑。

**版本号**：在 `app.config.ts` 中手动修改 `APP_VERSION`，不要通过环境变量或命令行注入。

| 后缀 | `EXPO_PUBLIC_APP_ENV` | API 地址 |
|------|----------------------|----------|
| `:test` | `test` | `EXPO_PUBLIC_API_BASE_URL_TEST` |
| `:prod` / 默认 | `production` | `EXPO_PUBLIC_API_BASE_URL_PROD` |

`app.config.ts` 同时支持 `APP_ENV`（EAS 构建用）与 `EXPO_PUBLIC_APP_ENV`（本地 script 用），未设置时默认 `production`。

可用 `EXPO_PUBLIC_API_BASE_URL` 覆盖 development 场景的 API 地址（仅本地调试时按需启用 `.env` 中的 `EXPO_PUBLIC_APP_ENV=development`）。

### `.env`（复制后按需填写）

```bash
EXPO_PUBLIC_UPLOAD_PROXY_URL=http://localhost:3099/upload
EXPO_PUBLIC_MOCK_SEND_QUOTA=0
EXPO_PUBLIC_MOCK_SEND_CLAIMED=1

# EXPO_PUBLIC_APP_ENV=test          # 也可在 .env 固定环境（默认由 pnpm script 注入，一般无需设置）
# EXPO_PUBLIC_API_BASE_URL=         # 覆盖 API 地址

EXPO_PUBLIC_WECHAT_APP_ID=
EXPO_PUBLIC_WECHAT_UNIVERSAL_LINK=
EXPO_PUBLIC_ALIPAY_APP_ID=
EXPO_PUBLIC_ALIPAY_SCHEME=
JPUSH_APP_KEY=
SENTRY_AUTH_TOKEN=
```

---

## 5. 本地启动命令

```bash
# 移动端（Expo Dev Client）
pnpm run start:test          # 测试环境
pnpm run start:prod          # 生产环境

# Web 端
pnpm run start:web:test
pnpm run start:web:prod

# 清缓存启动
pnpm run start:web:test -- -c

# 代码检查
pnpm run lint
```

### 真机原生调试（需先 `prebuild` 生成 `ios/` / `android/`）

```bash
pnpm run prebuild:test       # 或 prebuild:prod（版本号事先在 app.config.ts 修改）
pnpm run android:test        # Android
pnpm run ios:test            # iOS 真机（--device）
```

### EAS 云构建

```bash
pnpm run eas:android:test    # 测试包 Android
pnpm run eas:android:prod    # 生产包 Android
pnpm run eas:ios:test        # 测试包 iOS
pnpm run eas:ios:prod        # 生产包 iOS
```
