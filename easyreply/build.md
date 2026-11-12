# build

本仓库固定使用 **pnpm**（`pnpm-lock.yaml`）。请勿使用 `npm install`。

版本号在 `app.config.ts` 中手动修改 `APP_VERSION`，打包命令无需前缀版本号。

环境通过 pnpm script 后缀选择（`:test` 或 `:prod`），脚本内部会注入 `EXPO_PUBLIC_APP_ENV`。

## 0. 测试环境（test）

### 0.1 Web 本地测试（test）

```
pnpm run start:web:test -- -c
```

### 0.2 Web 打包（test）

```
pnpm run build:web:test
```

### 0.3 Android 本地测试（test）

```
pnpm run prebuild:test
pnpm run android:test
```

### 0.3.1 iOS 模拟器本地调试（test）

`start:web:test` **只给浏览器用**，不能给 Xcode / 模拟器提供原生 JS bundle。  
若用 Xcode 直接跑 Debug 却只开了 web Metro，会出现：

`No script URL provided… unsanitizedScriptURLString = (null)`

推荐流程（二选一）：

**方式 A（推荐，一条命令自动起 Metro + 装模拟器）：**

```
# 先停掉其它占用 8081 的 Metro（start:web / start:test:dev 都要关掉）
pnpm run ios:sim:test
```

不要同时开 `start:test:dev` 再跑 `ios:sim:test`（端口冲突时 App 会连错/连不到 Metro）。

**方式 B（自己开 Xcode）：**

```
# 终端只开这一个 Metro
pnpm run start:test:dev
# 然后 Xcode 打开 ios/app.xcworkspace，Scheme=Debug，选模拟器 Run
```

已注入模拟器 Metro localhost 回退；若刚改过 AppDelegate，Xcode 重新 Run 即可（不必每次 prebuild）。
若执行了 `prebuild --clean`，插件会自动重新写入该回退。

### 0.4 Android Release 打包（test）

```
pnpm run prebuild:test
pnpm run android:release:test
```

## 0. 生产环境（production）

### 0.1 Web 本地测试（production）

```
pnpm run start:web:prod -- -c
```

### 0.2 Web 打包（production）

```
pnpm run build:web:prod
```

### 验证dist

发版前请跑完这三步，尤其是 `smoke:web`——它能卡住「某个页面点进去整页崩溃、刷几次才好」这类问题。

```
# 1. 产物结构自检：跨 chunk 重复定义 / 悬空依赖 / 异步 chunk 文件缺失
pnpm run analyze:web

# 2. 本地起服务（缓存头与 gzip 行为对齐 nginx.conf）
pnpm run serve:web

# 3. 另开一个终端，用本机 Chrome 逐路由跑一遍，检查渲染结果与未捕获异常
pnpm run smoke:web

# 4. 校验发版自愈的版本判定（页面里读到的 entry 必须和 build-info.json 完全一致，
#    否则会变成「每次报错都刷新」）
pnpm run verify:web:version
```

`smoke:web` 全部 PASS 才算通过。想验手机端页面（窄屏走另一批 chunk）：

```
SMOKE_WIDTH=390 pnpm run smoke:web
```

### Web 首屏体积注意事项

Metro **不做 tree-shaking**，从 barrel 按名字导入会把整个包打进首屏：

- 图标必须从 `@/ui/web/antd-icons` 导入（内部走叶子路径）。直接从
  `@ant-design/icons` 导入会被 eslint 拦下——那样会把 847 个图标、约 6.6MB
  的 svg path 数据全打进包。新增图标先加到 `src/ui/web/antd-icons.ts`。
- Web 不按路由拆 chunk（`app.config.ts` 里 `asyncRoutes.web: false`）。实测拆包
  只把首屏 JS 从 2124KB 降到 2084KB（gzip，-1.9%），因为共用依赖最后都会被提到
  首屏同步加载的 `__common`；代价却是 55 个 chunk 和发版后的异步加载崩溃。
  需要延迟加载的重模块用 `webRoute` / `webComponent` 显式控制。

### 0.3 Android 本地测试（production）

```
pnpm run prebuild:prod
pnpm run android:prod
```

### 0.4 Android Release 打包（production）

```
pnpm run prebuild:prod
pnpm run android:release:prod
```
## 1. web

### 打包

```
pnpm run build:web:test
```

### 本地调试

```
pnpm run start:web:test -- -c
```

### 真机调试

```
pnpm run prebuild:test
pnpm run android:test --device
pnpm run ios:test --device
```

## 2. android

### 打包

第一步

```
pnpm run prebuild:test
```

> 注意：这个命令会重新生成 android 原生目录，手动写在 android/local.properties 里的 sdk.dir 也会被清掉
>
> 更稳妥的方式是提前在终端配置：
>
> ```
export ANDROID_HOME=$HOME/Library/Android/sdk
export ANDROID_SDK_ROOT=$HOME/Library/Android/sdk
export PATH=$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH
> ```
>
> 如果不想每次手动执行，可以把上面这几行写入 ~/.zshrc，然后执行 source ~/.zshrc

第二步

```
pnpm run android:release:test
```

> 打包好的app在android/app/build/outputs/apk/release下
>
> 改名为qinghui_版本号.apk 比如qinghui_v1.3.0.apk

## 新的打包逻辑
用法示例（macOS）

- 测试包（Android）：
```
pnpm run eas:android:test
```
- 生产包（iOS）：
```
pnpm run eas:ios:prod
```
校验

- 
### 本地调试
```
npx expo prebuild --clean
```
```
npx expo run:android
```
```
真机调试可以安装android/app/build/outputs/apk/debug下的apk,扫码本机调试(需要和电脑在同一局域网下)
```
