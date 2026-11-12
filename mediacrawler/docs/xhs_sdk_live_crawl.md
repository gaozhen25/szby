# 小红书 SDK 实时爬取技术文档

> 爬虫侧：`keyword_ex` / `creator_ex` 实时爬取，返回 dict，并写入 JSON。  
> 后端侧：读 ``data/xhs/json/`` 下的 JSON，**无需浏览器、无需起服务**。

---

## 1. 能力概述

| 角色 | 入口 | 是否需要浏览器 | 作用 |
|------|------|----------------|------|
| **爬虫同事（你）** | `keyword_ex` / `creator_ex` | **是** | 爬取 → 返回 dict → 写 JSON |
| **后端同事** | `XhsBackendClient.archive.local()` | **否** | 读 JSON → 返回 dict |

| 接口 | 爬虫侧 | 后端侧 |
|------|--------|--------|
| 关键词搜索 | `keyword_ex("xhs", keyword) -> dict` | `client.search(keyword) -> dict` |
| 博主爬取 | `creator_ex("xhs", creator_id) -> dict` | `client.creator(nickname) -> dict` |

**当前支持平台：** 仅 `xhs`（小红书）。

---

## 1.1 后端同事怎么用（无浏览器，读 JSON）

你爬完后，JSON 在 ``data/xhs/json/{关键词或昵称}_{日期}.json``。  
后端指向同一目录（或拷贝过去）即可：

```python
from sdk import XhsBackendClient

client = XhsBackendClient.archive.local()   # 默认 data/xhs/json/
# 或指定目录：XhsBackendClient.archive.local(json_dir="/path/to/json")

result = client.search("美女")
print(result["code"])
print(result["data"]["summary"]["note_count"])
print(result["data"]["notes"][0]["title"])

profile = client.creator("火星生活")   # 按博主昵称匹配 JSON 文件名
print(profile["data"]["profile"]["nickname"])
print(profile["data"]["notes"][0]["title"])
```

后端也可以不用 SDK，直接 ``json.load`` 读文件：

```python
import json
from pathlib import Path

path = Path("data/xhs/json/美女_2026-07-10.json")
payload = json.loads(path.read_text(encoding="utf-8"))
notes = payload["data"]["notes"]
```

---

## 2. 整体架构

```
你（爬虫）                          后端
    │                                  │
keyword_ex / creator_ex                │
    │                                  │
    ▼                                  │
爬虫 → 内存封装 → dict 返回             │
    │                                  │
    └─► data/xhs/json/*.json ─────────► XhsBackendClient.archive.local()
                                       或 json.load 读文件
                                       → dict
```

核心原则：**爬取不写 CSV**；爬完即写 JSON；后端只读 JSON，不触发爬虫。

---

## 3. 核心逻辑

### 3.1 关键词搜索 `keyword_ex`

**流程：**

1. 校验 `platform`、`keyword`
2. `reset_memory_collector()` 清空上次内存数据
3. 临时覆盖配置：
   - `CRAWLER_TYPE = "search"`
   - `KEYWORDS = keyword`
   - `SAVE_DATA_OPTION = "memory"`
4. 启动 `XiaoHongShuCrawler`，执行 `search()`：
   - 按关键词分页搜索
   - 拉笔记详情 → `update_xhs_note()` → 内存
   - 可选拉评论 → `update_xhs_note_comment()` → 内存
5. 从内存按 `source_keyword` 过滤笔记，构建 `XhsSearchDataset`
6. `XhsSearchService.to_api_response()` 返回标准 dict

**注意：** 小红书搜索每页固定 20 条，`max_notes_count` 小于 20 时会被爬虫内部抬到 20。

### 3.2 博主爬取 `creator_ex`

**流程：**

1. 校验 `platform`、`creator_id`
2. `_normalize_creator_id()` 解析博主参数：
   - 完整主页 URL（含 `xsec_token`）→ 原样或规范化 URL
   - 24 位 hex `user_id` → 直接使用
3. 临时覆盖配置：
   - `CRAWLER_TYPE = "creator"`
   - `XHS_CREATOR_ID_LIST = [creator_target]`
   - `SAVE_DATA_OPTION = "memory"`
4. 启动爬虫，执行 `get_creators_and_notes()`：
   - 拉博主 profile → `save_creator()` → 内存
   - 拉博主笔记列表与详情 → 内存
5. 构建 `XhsCreatorDataset`（profile + notes）
6. `XhsCreatorService.to_api_response()` 返回 dict

### 3.3 内存存储

`MemoryCollector` 三个容器：

| 字段 | 用途 | 写入时机 |
|------|------|----------|
| `creator` | 博主简介 | `store_creator()` |
| `notes` | 笔记（按 `note_id` 去重） | `store_content()` |
| `comments` | 评论（按 `comment_id` 去重） | `store_comment()` |

注册方式：在 `XhsStoreFactory.STORES` 中增加 `"memory": XhsMemoryStoreImplement`，爬虫写数据时与普通 CSV 模式走同一套 `store.xhs.update_xhs_note` 链路，只是落盘目标改为内存。

---

## 4. 调用方式

### 4.1 入口类

```python
from sdk import MediaCrawlerSDK

sdk = MediaCrawlerSDK()
```

### 4.2 `keyword_ex` — 关键词搜索

**同步（脚本 / 普通 Python）：**

```python
result = sdk.keyword_ex(
    platform="xhs",
    keyword="火星生活",
    max_notes_count=20,       # 可选，最多爬多少条笔记
    enable_comments=False,    # 可选，是否爬评论
    login_type="qrcode",      # qrcode | phone | cookie
    cookies="",               # login_type=cookie 时传入
    start_page=1,             # 从第几页开始
    headless=None,            # None=用 config 默认；True/False 覆盖
)
```

**异步（FastAPI / asyncio）：**

```python
result = await sdk.keyword_ex_async("xhs", "火星生活", max_notes_count=20)
```

**函数签名：**

```python
def keyword_ex(
    platform: str,
    keyword: str,
    *,
    login_type: str = "qrcode",
    max_notes_count: int | None = None,
    enable_comments: bool = False,
    enable_sub_comments: bool = False,
    headless: bool | None = None,
    cookies: str = "",
    start_page: int = 1,
) -> dict
```

**底层服务函数（不经过 SDK 类）：**

```python
from services import run_keyword_search
import asyncio

result = asyncio.run(run_keyword_search("xhs", "火星生活", max_notes_count=20))
```

### 4.3 `creator_ex` — 博主信息

**同步：**

```python
# 方式 1：24 位 user_id
result = sdk.creator_ex("xhs", "5aa2b1c8e8ac2b2b0f0130fe")

# 方式 2：完整主页 URL（推荐，含 xsec_token 更稳定）
result = sdk.creator_ex(
    "xhs",
    "https://www.xiaohongshu.com/user/profile/5aa2b1c8e8ac2b2b0f0130fe?xsec_token=xxx&xsec_source=pc_search",
    max_notes_count=30,
    enable_comments=False,
)
```

**异步：**

```python
result = await sdk.creator_ex_async("xhs", "5aa2b1c8e8ac2b2b0f0130fe", max_notes_count=5)
```

**函数签名：**

```python
def creator_ex(
    platform: str,
    creator_id: str,
    *,
    login_type: str = "qrcode",
    max_notes_count: int | None = None,
    enable_comments: bool = False,
    enable_sub_comments: bool = False,
    headless: bool | None = None,
    cookies: str = "",
) -> dict
```

**底层服务函数：**

```python
from services import run_creator_crawl
import asyncio

result = asyncio.run(run_creator_crawl("xhs", "5aa2b1c8e8ac2b2b0f0130fe", max_notes_count=5))
```

---

## 5. 返回数据结构

### 5.1 `keyword_ex` 返回值

与 HTTP `GET /api/data/search-export` 一致：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "keywords": ["火星生活"],
    "notes": [
      {
        "note_id": "...",
        "title": "...",
        "desc": "...",
        "liked_count": "31",
        "source_keyword": "火星生活",
        "note_url": "...",
        "xsec_token": "..."
      }
    ],
    "comments": [],
    "grouped_notes": {
      "火星生活": [ /* 同上 notes */ ]
    },
    "summary": {
      "source_file": "memory",
      "keywords": ["火星生活"],
      "note_count": 20,
      "comment_count": 0,
      "notes_per_keyword": {"火星生活": 20}
    }
  }
}
```

**常用读取：**

```python
result["code"]                              # 0 表示成功
result["data"]["summary"]["note_count"]     # 笔记总数
result["data"]["notes"]                     # 笔记列表
result["data"]["notes"][0]["title"]         # 首条标题
```

### 5.2 `creator_ex` 返回值

与博主 export API 一致：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "profile": {
      "user_id": "5aa2b1c8e8ac2b2b0f0130fe",
      "nickname": "火星生活",
      "gender": "Female",
      "fans": "23",
      "follows": "12",
      "ip_location": "上海",
      "desc": "还没有简介",
      "avatar": "https://...",
      "interaction": "121",
      "tag_list": "{\"info\": \"32岁\", \"location\": \"上海浦东新区\"}"
    },
    "notes": [
      {
        "note_id": "...",
        "title": "...",
        "creator_hash": "5aa2b1c8e8ac2b2b0f0130fe",
        "liked_count": "31"
      }
    ],
    "summary": {
      "source_file": "memory",
      "nickname": "火星生活",
      "fans": "23",
      "follows": "12",
      "ip_location": "上海",
      "note_count": 5
    }
  }
}
```

**常用读取：**

```python
result["data"]["profile"]["nickname"]
result["data"]["profile"]["fans"]
result["data"]["notes"]
len(result["data"]["notes"])
```

---

## 6. 运行命令速查

> 以下命令均在项目根目录执行：`cd /path/to/MediaCrawler`

### 6.0 最简命令（推荐）

```bash
# 关键词搜索 → data/xhs/json/{关键词}_{日期}.json
./mc search 火星生活

# 博主爬取 → data/xhs/json/{昵称}_{日期}.json
./mc creator 5aa2b1c8e8ac2b2b0f0130fe

# 博主主页 URL（推荐，含 xsec_token 更稳定；URL 必须用引号）
./mc creator "https://www.xiaohongshu.com/user/profile/5aa2b1c8e8ac2b2b0f0130fe?xsec_token=xxx&xsec_source=pc_search"

# 限制条数
./mc search 火星生活 -n 5
./mc creator 5aa2b1c8e8ac2b2b0f0130fe -n 5

# 爬评论
./mc search 火星生活 -c
```

等价写法：

```bash
uv run python sdk_cli.py search 火星生活
```

查看帮助：

```bash
./mc --help
./mc search --help
```

---

### 6.1 环境准备

```bash
cd /Users/gzbytech.tech/spider/MediaCrawler
uv sync
```

需本机安装 Chrome（默认 CDP 模式）。首次运行需扫码登录；登录态在 `browser_data/`。

---

### 6.2 关键词搜索 `keyword_ex`

**基础（同步，写 JSON 到 `data/xhs/json/{关键词}_{日期}.json`）：**

```bash
uv run python -c "
from sdk import MediaCrawlerSDK
r = MediaCrawlerSDK().keyword_ex('xhs', '火星生活', max_notes_count=20)
print(r['data']['summary'])
"
```

**完整输出（含首条笔记标题、JSON 路径）：**

```bash
uv run python - <<'PY'
import json
from sdk import MediaCrawlerSDK

result = MediaCrawlerSDK().keyword_ex(
    "xhs", "火星生活",
    max_notes_count=20,
    enable_comments=False,
)
print("code:", result["code"])
print("json:", result["data"]["summary"]["source_file"])
print("summary:", json.dumps(result["data"]["summary"], ensure_ascii=False, indent=2))
if result["data"]["notes"]:
    print("首条:", result["data"]["notes"][0]["title"])
PY
```

**带评论爬取：**

```bash
uv run python -c "
from sdk import MediaCrawlerSDK
r = MediaCrawlerSDK().keyword_ex('xhs', '火星生活', max_notes_count=20, enable_comments=True)
print('notes:', len(r['data']['notes']), 'comments:', len(r['data']['comments']))
"
```

**Cookie 登录：**

```bash
uv run python -c "
from sdk import MediaCrawlerSDK
r = MediaCrawlerSDK().keyword_ex('xhs', '火星生活', login_type='cookie', cookies='你的cookie')
print(r['data']['summary'])
"
```

**异步（FastAPI / asyncio 脚本内）：**

```bash
uv run python - <<'PY'
import asyncio
from sdk import MediaCrawlerSDK

async def main():
    r = await MediaCrawlerSDK().keyword_ex_async("xhs", "火星生活", max_notes_count=20)
    print(r["data"]["summary"])

asyncio.run(main())
PY
```

**底层服务函数（不经过 SDK 类）：**

```bash
uv run python - <<'PY'
import asyncio
from services import run_keyword_search

r = asyncio.run(run_keyword_search("xhs", "火星生活", max_notes_count=20))
print(r["data"]["summary"])
PY
```

---

### 6.3 博主爬取 `creator_ex`

**基础（user_id）：**

```bash
uv run python -c "
from sdk import MediaCrawlerSDK
r = MediaCrawlerSDK().creator_ex('xhs', '5aa2b1c8e8ac2b2b0f0130fe', max_notes_count=5)
print(r['data']['summary'])
"
```

**完整输出（profile + JSON 路径）：**

```bash
uv run python - <<'PY'
import json
from sdk import MediaCrawlerSDK

result = MediaCrawlerSDK().creator_ex(
    "xhs",
    "5aa2b1c8e8ac2b2b0f0130fe",
    max_notes_count=5,
    enable_comments=False,
)
print("code:", result["code"])
print("json:", result["data"]["summary"]["source_file"])
print("profile:", json.dumps(result["data"]["profile"], ensure_ascii=False, indent=2))
print("notes 数量:", len(result["data"]["notes"]))
PY
```

**主页 URL（含 xsec_token，更稳定）：**

```bash
uv run python -c "
from sdk import MediaCrawlerSDK
url = 'https://www.xiaohongshu.com/user/profile/5aa2b1c8e8ac2b2b0f0130fe?xsec_token=xxx&xsec_source=pc_search'
r = MediaCrawlerSDK().creator_ex('xhs', url, max_notes_count=5)
print(r['data']['summary'])
"
```

**异步：**

```bash
uv run python - <<'PY'
import asyncio
from sdk import MediaCrawlerSDK

async def main():
    r = await MediaCrawlerSDK().creator_ex_async(
        "xhs", "5aa2b1c8e8ac2b2b0f0130fe", max_notes_count=5
    )
    print(r["data"]["summary"])

asyncio.run(main())
PY
```

**底层服务函数：**

```bash
uv run python - <<'PY'
import asyncio
from services import run_creator_crawl

r = asyncio.run(run_creator_crawl("xhs", "5aa2b1c8e8ac2b2b0f0130fe", max_notes_count=5))
print(r["data"]["summary"])
PY
```

---

### 6.4 后端 dict 调用测试

#### A. 单元测试（无需浏览器）

```bash
cd /Users/gzbytech.tech/spider/MediaCrawler
uv run pytest tests/test_xhs_json_service.py tests/test_sdk_extractor_api_dict.py -q
```

#### B. 读本地 JSON（模拟后端，无需浏览器）

已有 `data/xhs/json/美女_2026-07-10.json` 时：

```bash
uv run python - <<'PY'
from sdk import XhsBackendClient

client = XhsBackendClient.archive.local()
result = client.search("美女")
print("code:", result["code"])
print("note_count:", result["data"]["summary"]["note_count"])
print("首条标题:", result["data"]["notes"][0]["title"])
PY
```

#### C. 爬虫本机爬取（需浏览器）

```bash
./mc search 火星生活
# 或
uv run python -c "from sdk import keyword_ex; r=keyword_ex('xhs','火星生活',max_notes_count=5); print(r['data']['summary'])"
```

爬完后用 B 的步骤验证后端能读到 JSON。

---

### 6.5 JSON 落盘与去重验证

**查看今日生成的 JSON：**

```bash
ls -lt data/xhs/json/
```

**再次运行同一关键词（验证去重追加，不覆盖旧 note_id）：**

```bash
uv run python -c "
from sdk import MediaCrawlerSDK
r = MediaCrawlerSDK().keyword_ex('xhs', '火星生活', max_notes_count=20)
print('note_count:', r['data']['summary']['note_count'])
print('file:', r['data']['summary']['source_file'])
"
```

**格式化查看 JSON 摘要：**

```bash
uv run python -c "
import json, glob
f = sorted(glob.glob('data/xhs/json/火星生活_*.json'))[-1]
d = json.load(open(f, encoding='utf-8'))
print(f, 'notes:', len(d['data']['notes']))
"
```

---

### 6.5 单元测试（不启动浏览器）

```bash
# 内存爬取 + 数据组装
uv run pytest tests/test_sdk_extractor.py -v

# JSON 落盘 + 去重合并
uv run pytest tests/test_sdk_json_export.py -v

# memory store 工厂
uv run pytest tests/test_store_factory.py -v

# 全部 SDK 相关测试
uv run pytest tests/test_sdk_extractor.py tests/test_sdk_json_export.py tests/test_store_factory.py -v
```

---

### 6.6 旧模式：读 CSV（`XhsDataClient`，非实时爬取）

```bash
# 需先有 CSV 文件
uv run python examples/xhs_sdk_integration.py
```

```bash
uv run python -c "
from sdk import XhsDataClient
ds = XhsDataClient.local().search.load(keyword='火星生活')
print(ds.note_count, ds.source_file)
"
```

---

### 6.7 等价 CLI（写 CSV，非 SDK 实时路径）

```bash
# 关键词 → data/xhs/csv/{关键词}_{日期}.csv
uv run main.py --platform xhs --type search --lt qrcode --keywords "火星生活"

# 博主 → data/xhs/csv/{昵称}_{日期}.csv
uv run main.py --platform xhs --type creator --lt qrcode \
  --creator_id "5aa2b1c8e8ac2b2b0f0130fe"
```

---

### 6.8 命令对照表

| 逻辑 | 最简命令 | 输出位置 |
|------|----------|----------|
| 关键词实时爬取 | `./mc search 火星生活` | `data/xhs/json/{关键词}_{日期}.json` |
| 博主实时爬取 | `./mc creator {user_id}` | `data/xhs/json/{昵称}_{日期}.json` |
| 关键词读历史 CSV | `XhsDataClient.local().search.load(...)` | `data/xhs/csv/` |
| 博主读历史 CSV | `XhsDataClient.local().creator.load(...)` | `data/xhs/csv/` |
| CLI 爬取写 CSV | `uv run main.py --type search/creator` | `data/xhs/csv/` |

---

## 7. 源码文件索引

| 路径 | 说明 |
|------|------|
| `mc` | **最简 CLI**（`./mc search` / `./mc creator`） |
| `sdk_cli.py` | CLI 实现（Typer） |
| `sdk/extractor.py` | `MediaCrawlerSDK` 类，`keyword_ex` / `creator_ex` 对外入口 |
| `sdk/__init__.py` | 导出 `MediaCrawlerSDK` |
| `services/crawler_runner.py` | `run_keyword_search`、`run_creator_crawl`、config 覆盖与内存组装 |
| `store/memory_collector.py` | 单次爬取的内存数据容器 |
| `store/xhs/_store_impl.py` | `XhsMemoryStoreImplement` |
| `store/xhs/__init__.py` | 注册 `memory` 存储类型 |
| `services/sdk_json_export.py` | JSON 落盘：``{关键词/昵称}_{日期}.json``，去重合并 |
| `tests/test_sdk_extractor.py` | 单元测试 |

---

## 8. 异常与注意事项

### 8.1 异常

```python
from sdk import MediaCrawlerSDK, SdkError

sdk = MediaCrawlerSDK()

try:
    result = sdk.keyword_ex("xhs", "火星生活")
except SdkError as e:
    # 参数错误、async 上下文误用 sync 方法等
    print(e)
```

| 场景 | 现象 | 处理 |
|------|------|------|
| 在 async 里调用 `keyword_ex()` | `SdkError: 不能在 async 上下文...` | 改用 `keyword_ex_async()` |
| `platform` 非 xhs | `SdkError: 暂不支持的平台` | 目前仅 xhs |
| `keyword` / `creator_id` 为空 | `SdkError` | 检查入参 |
| 未登录 / 登录过期 | 浏览器停登录页或 notes 为空 | 扫码登录或传 `cookies` |
| CDP 连接失败 | 启动浏览器超时 | 确认 Chrome 已开远程调试 9222，或改 config |

### 8.2 性能与行为

1. **耗时长**：单次调用通常 20 秒～数分钟（浏览器 + 登录 + 爬取间隔 sleep）。
2. **JSON 落盘**：自动写入 `data/xhs/json/{关键词}_{日期}.json` 或 `data/xhs/json/{博主昵称}_{日期}.json`；同日重复调用按 `note_id` / `comment_id` 去重追加，不覆盖旧数据。
3. **并发**：每次调用会启动/连接浏览器，不建议高并发；生产环境宜加队列或限流。
4. **config 隔离**：爬取时临时覆盖 `config`，结束后自动恢复，不影响全局配置。
5. **评论**：默认 `enable_comments=False`；开启后耗时会明显增加。

---

## 9. 一页速查

```python
from sdk import MediaCrawlerSDK

sdk = MediaCrawlerSDK()

# 关键词搜索 → dict
search = sdk.keyword_ex("xhs", "火星生活", max_notes_count=20)
notes = search["data"]["notes"]

# 博主信息 → dict
creator = sdk.creator_ex("xhs", "5aa2b1c8e8ac2b2b0f0130fe", max_notes_count=5)
profile = creator["data"]["profile"]
posts = creator["data"]["notes"]
```

```bash
./mc search 火星生活
./mc creator 5aa2b1c8e8ac2b2b0f0130fe
uv run pytest tests/test_sdk_extractor.py tests/test_sdk_json_export.py -v
```

---

## 10. 相关文档

| 文档 | 说明 |
|------|------|
| [xhs_sdk_guide.md](./xhs_sdk_guide.md) | 读 CSV 模式（`XhsDataClient`） |
| [xhs_data_api.md](./xhs_data_api.md) | HTTP API 与字段说明 |
