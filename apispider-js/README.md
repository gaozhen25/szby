# XHS / Douyin Spider

小红书、抖音关键词搜索、博主作品与单条内容采集（本地学习用）。

仓库：`ssh://git@8.216.41.144:2424/gaozhen/apispider.git`

## 目录

```
platforms/
  xhs/          # 小红书：client / help(签名) / normalize / cli
  douyin/       # 抖音：client / help(a_bogus) / normalize / cli
  dyhot/        # 抖音热点宝：搜索热点总榜
  common/       # cookie JSON、并行、落盘
vendor/
  douyin.js     # 抖音 a_bogus 签名脚本
cookies/        # 本地 cookie（gitignore）：cookies.json
examples/cookies/  # cookie JSON 示例
data/           # 输出 JSON
docs/           # 字段技术文档等
main.py         # 统一入口
```

**JSON 字段说明**：[docs/CRAWLER_FIELDS.md](docs/CRAWLER_FIELDS.md)（抖音 creator 作品/评论/断点）

## 环境

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# 抖音 a_bogus 需要本机已安装 Node.js
```

## Cookie（单个 JSON）

```bash
mkdir -p cookies
cp examples/cookies/cookies.json cookies/cookies.json
```

格式：

```json
{
  "xhs": ["cookie字符串1", "cookie字符串2"],
  "dy": ["cookie字符串1"],
  "dyhot": [],
  "ks": []
}
```

- 同一平台数组里可放多个 cookie；多关键词搜索时按数量并行
- `dyhot` 为空时会回退使用 `dy`
- 也可用环境变量 `XHS_COOKIE` / `DY_COOKIE` / `DYHOT_COOKIE`
- `--account 1` 或 `--account xhs_1` 指定第几个账号

### 小红书扫码登录（默认 CDP）

```bash
pip install playwright
playwright install chromium   # --playwright 旧模式才需要
# 需本机已装 Google Chrome（或设 XHS_CHROME_PATH）
python scripts/xhs_qr_login.py                 # CDP：每次重新扫码，登录态写入 profile
python scripts/xhs_qr_login.py --name 账号A    # 指定账号键 / profile 名
python scripts/xhs_qr_login.py --cdp-port 9333
python scripts/xhs_qr_login.py --playwright    # 旧 Playwright Chromium
python scripts/xhs_qr_login.py --playwright --reuse 账号A
```

CDP：启动本机 Chrome（`--user-data-dir=cookies/xhs_cdp_profiles/<名>`），每次清会话后重新扫码；扫码成功后 cookie 写入 `cookies.json`，浏览器 profile 保留。  
终端只输出状态。成功后保存：
- `cookies/cookies.json` 的 `xhs` 数组
- `cookies/xhs_states/<账号键>.json`
- `cookies/xhs_cdp_profiles/<账号键>/`（Chrome 持久化目录）
- `cookies/xhs_states/index.json`

### 服务器扫码登录（抖音 + 小红书）

适合无图形界面的机器：HTTP 出二维码，手机扫码后 cookie 写入 `cookies/cookies.json`。

详见 [docs/LOGIN_SERVER.md](docs/LOGIN_SERVER.md)。

```bash
pip install playwright flask
playwright install chromium
python scripts/login_server.py --host 0.0.0.0 --port 8787
# 浏览器打开 http://服务器IP:8787/ 选平台扫码
# 本机调试可弹出浏览器：LOGIN_HEADED=1 python scripts/login_server.py --port 8787
```

| 方式 | 场景 |
|------|------|
| `scripts/login_server.py` | 服务器部署拿 cookie（推荐） |
| `scripts/xhs_qr_login.py` | 本机小红书 CDP 精细登录 |

## 用法

```bash
source .venv/bin/activate

python main.py xhs search 美食
python main.py xhs search 美食 旅游 穿搭          # 多关键词并行
python main.py xhs search 美食,旅游 --workers 2
python main.py dy search 美食 篮球
python main.py dyhot search-board
python main.py xhs creator '主页URL' --account main
python main.py dy creator '主页URL'
python main.py dy creator 抖音号 --all --with-comments   # 简介+全部作品+全量评论(含二级)
python main.py dy creator '主页URL' --all --excel --interval 3
# --excel：写出 xlsx（标题/标签/嵌入图片）；图片缓存 data/dy/media/{昵称}/，失败可重跑续下
# 默认断点续爬 data/dy/checkpoints/{sec_uid}.json；Ctrl+C 也会保存；连续 403 自动换 cookies.json 里其它 dy 号
# 强制重来: --fresh ；重爬作品保留评论: --refetch-posts ；禁用换号: --no-rotate-cookies
python main.py xhs detail 'https://www.xiaohongshu.com/explore/NOTE_ID?xsec_token=...'
python main.py dy detail 'https://www.douyin.com/video/AWEME_ID'
python main.py xhs profile
python main.py dy profile 抖音号
python main.py xhs im dump                    # 拉全部私信会话+历史
python main.py xhs im poll --poll-interval 2  # 轮询新私信（Ctrl+C 结束）
python main.py dy im dump --nick 顾清寒          # 每个会话一个 JSON：昵称_抖音号.json，按时间像微信
python main.py dy im poll --nick 9277 --poll-interval 2   # 监听全部会话
python main.py dy im poll --nick 顾清寒 --poll-interval 2  # 监听全部会话（不自动回复）
python main.py dy im send --nick 9277 --text '你好'       # 回复当前会话
python main.py dy im send --nick 9277 --to 对方抖音号 --text '你好'
python main.py dy im send --nick 9277 --to 号1,号2,号3 --text '你好' --workers 3
# 收发都只需 cookies.json；发信缺 ticket 时会用 cookie 补抓（失败再加 --headed）
```

小红书搜索：`POST https://so.xiaohongshu.com/api/sns/web/v2/search/notes`  
单条：`crawl_type=detail`  
`profile`：登录态或按号反查主页。  
小红书私信：`chats` 列会话 + `messages/history` 拉历史（需登录 cookie）。  
抖音私信：`imapi` protobuf — `conversation/get_list`(200) 列会话；`get_by_conversation`(301) 轮询；`conversation/create`(609)+`message/send`(100) 发信。用户侧只需 `cookies.json`；发信内部会用 cookie 补抓 `web_protect` ticket。默认监听全部会话，`--conversation-id` 可钉死某一个。

## JSON 输出

```
data/xhs/json/{关键词|昵称|笔记ID}_{YYYY-MM-DD}.json
data/xhs/im/{昵称}_{YYYY-MM-DD}.json
data/dy/json/{关键词|昵称|作品ID}_{YYYY-MM-DD}.json
data/dy/excel/{昵称}_{YYYY-MM-DD}.xlsx
data/dy/media/{昵称}/                 # Excel 图片本地下载缓存（断点续下）
data/dy/im/{自己昵称}/{对方昵称}_{抖音号}.json
data/dyhot/json/搜索热点总榜_{YYYY-MM-DD}.json
```
