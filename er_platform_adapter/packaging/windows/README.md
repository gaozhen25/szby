# Windows exe 打包（在 macOS / Linux 上交叉构建）

`adapter.exe` 是 PC 端（BOSS/抖音消息 Adapter + 轻回桌面连接器）的单文件可执行程序，
`adapter-gateway.exe` 是服务端控制 Gateway。两者均为一键式单文件 exe，目标 Windows
机器**不需要安装 Python**，但运行平台登录功能需要已安装 **Google Chrome**（与当前
README 要求一致）。

## 为什么需要 Wine

PyInstaller 不支持跨平台编译：Windows exe 必须在 Windows 环境里构建。本项目用
**Docker + Wine + Windows 版 Python 3.11 + PyInstaller** 在 macOS/Linux 上完成交叉构建，
构建产物就是原生 Windows PE 可执行文件。

## 一键构建

```bash
# 需要 Docker 已启动（Docker Desktop / colima 等）
bash packaging/windows/build-on-mac.sh
```

脚本会：

1. 构建 `adapter-win-build` 镜像（首次需下载约 1GB，耗时数分钟，之后复用）；
2. 在容器内用 Wine 静默安装 Windows Python 3.11.9；
3. 安装全部运行依赖（playwright、aio-pika、paho-mqtt、execjs、grpcio 等）；
4. 用 PyInstaller 产出单文件 `adapter.exe`、`adapter-gateway.exe`；
5. 在容器内用 Wine 做冒烟测试（`--version`、`--help`、`doctor --skip-platform`、
   以及 `run` 单实例锁测试）。

产物输出到 `<repo>/build_win/dist/`。

## 手动分步构建（可复现）

```bash
docker build -t adapter-win-build:latest -f packaging/windows/Dockerfile packaging/windows

docker run --rm \
  -v "$(pwd):/src" \
  -v "$(pwd)/packaging/windows:/build" \
  adapter-win-build:latest \
  bash /build/build.sh
```

容器内 `/src/build_win/dist/` 即为产物目录。也可以只构建其中一个：

```bash
# 容器内执行
wine python.exe -m PyInstaller --noconfirm --clean --distpath dist --workpath work adapter.spec
wine python.exe -m PyInstaller --noconfirm --clean --distpath dist --workpath work gateway.spec
```

## 在 Windows 上使用 adapter.exe

1. 把 `adapter.exe` 放到一个空目录（例如 `C:\adapter\`）。
2. 同目录放 `.env`（内容与仓库 `.env.example` 一致，填入 RabbitMQ、Gateway 等配置）。
3. 双击运行，或在命令行执行：

```bat
adapter.exe serve --dotenv .env
```

启动后自动打开浏览器 `http://127.0.0.1:8765/`，操作方式与源码运行完全一致。

全部子命令均可用：`serve` / `run` / `doctor` / `mq-watch` / `backfill` / `reset`，
以及 `boss|douyin login|logout|status|conversations|messages|send`。

要点：

- `.env` 与 `adapter_data/`（状态库、Chrome Profile）都相对于**当前工作目录**，
  建议始终在 `adapter.exe` 所在目录启动，或显式传 `--dotenv`。
- 首次启动 Windows 安全中心/杀毒软件可能对未签名 exe 弹窗，选择“仍要运行”即可；
  正式分发建议用代码签名证书签名。
- 抖音签名强制使用 Node.js：优先 exe 同目录的 `node.exe`（构建时从 Playwright
  driver 拷出），否则从包内释放到 `adapter_data/runtime/node.exe`，不再使用
  Windows JScript（会触发 `SyntaxError: 缺少 ')'`）。
- 分发时请把 `adapter.exe` 与 `node.exe` 放在同一目录。
- 平台登录需要目标机器安装 Google Chrome（项目使用 `channel="chrome"` 复用本机
  Chrome，不打包浏览器）。

## 目录说明

| 文件 | 作用 |
|---|---|
| `Dockerfile` | Wine 交叉构建镜像（Debian + wine64 + xvfb） |
| `build.sh` | 容器内构建 + 冒烟测试脚本 |
| `build-on-mac.sh` | macOS/Linux 一键构建入口 |
| `entry_adapter.py` / `entry_gateway.py` | PyInstaller 入口脚本 |
| `adapter.spec` / `gateway.spec` | PyInstaller 打包配置（含 web 资源、douyin.js、playwright driver） |
