# 浏览器 Cookie 同步

`sync_cookies.sh` 会读取本机 Chrome、Edge、Brave、Arc、Chromium、Firefox、Safari
以及抖音 macOS 客户端中的抖音/小红书登录态，生成后端 Cookie 池并上传到服务器。

## 首次准备

后端 Python 命令必须使用 `starx` conda 环境：

```bash
conda run --no-capture-output -n starx pip install browser-cookie3
```

macOS 会保护浏览器数据库和钥匙串。首次运行时，请允许钥匙串访问；若出现
`authorization denied`，在“系统设置 → 隐私与安全性 → 完全磁盘访问权限”中允许你运行
脚本所用的终端，然后重新打开终端。

## 使用

在 `starx-backend` 目录执行：

```bash
./sync_cookies.sh
```

默认行为：

- 本地写入 `cookies/cookies.json`，权限为 `0600`；
- 通过 SSH 配置中的 `starx` 别名上传；
- 远程写入 `~/projects/starx-backend/cookies/cookies.json`；
- 上传使用临时文件和原子替换，不会暴露半写入文件；
- 默认不在终端打印 Cookie 内容；
- 若抖音或小红书任一登录态缺失，则不上传。

只生成本地文件：

```bash
./sync_cookies.sh --no-upload
```

指定其他 SSH 别名：

```bash
./sync_cookies.sh --host lingyao
```

仅更新找到的平台，并保留本地文件中缺失平台的旧值：

```bash
./sync_cookies.sh --allow-partial
```

将完整 Cookie 原文打印到控制台（敏感信息可能被终端日志、录屏或历史记录保存）：

```bash
./sync_cookies.sh --print-cookies
```

不要使用 `sudo`。macOS 的浏览器数据库权限应通过“系统设置 → 隐私与安全性 →
完全磁盘访问权限”授予 Terminal 或 iTerm；授权后应彻底退出并重新打开终端。

Cookie 文件已被 `.gitignore` 排除，不应手工加入 Git。
