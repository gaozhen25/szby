# 小红书数据 SDK 使用指南（后端版）

> 面向后端同事：说明 SDK 是做什么的、怎么接入、常用代码怎么写。  
> 当前 SDK 覆盖 **小红书（xhs）** 的 **关键词搜索** 与 **博主** 两类数据。

> **实时爬取模式（新）：** 爬虫 ``keyword_ex`` / ``creator_ex`` 返回 dict 并写 JSON；后端读 JSON，见 [xhs_sdk_live_crawl.md](./xhs_sdk_live_crawl.md)。

---

## 1. SDK 是做什么的？

爬虫跑完后，数据会写入 CSV 文件（默认目录 `data/xhs/csv/`）。  
后端不需要自己解析 CSV，也不需要手写 HTTP 请求参数，**通过 SDK 一行代码拿到结构化 Python 对象或入库用的 dict**。

```
爬虫写入 CSV  →  SDK 读取 / 解析  →  后端业务（入库、接口、定时任务）
```

SDK 封装了：

| 能力 | 说明 |
|------|------|
| 读 CSV | 自动识别文件命名、按关键词/昵称匹配最新文件 |
| 结构化对象 | 返回 Pydantic 模型（`XhsSearchNote`、`XhsCreatorProfile` 等） |
| 入库格式 | `to_db_records()` 直接输出 dict，字段与 CSV 列一致 |
| API 同构 | `export()` 与 HTTP 接口返回结构相同，方便本地/远程切换 |
| 双模式 | **local** 同机读文件；**remote** 跨服务调 FastAPI |

**推荐原则：** 新代码统一 `from sdk import XhsDataClient`，不要直接读 CSV 或重复写解析逻辑。

---

## 2. 前置条件

### 2.1 环境

在项目根目录，使用项目自带的 Python 环境：

```bash
cd /path/to/MediaCrawler
uv sync          # 首次安装依赖
```

后端代码需能 `import sdk`（同仓库部署时，把项目根目录加入 `PYTHONPATH`，或在项目内运行）。

### 2.2 数据从哪来？

SDK **只读数据，不负责爬取**。数据需由爬虫同事先生成：

```bash
# 关键词搜索（生成 美食_2026-07-07.csv）
uv run main.py --platform xhs --type search --lt qrcode --keywords "美食"

# 博主主页（生成 爱吃的胖泽_2026-07-08.csv）
uv run main.py --platform xhs --type creator --lt qrcode --creator "https://www.xiaohongshu.com/user/profile/xxx"
```

### 2.3 文件命名规则

| 类型 | 文件名示例 | 说明 |
|------|-----------|------|
| 关键词搜索 | `美食_2026-07-07.csv` | `{关键词}_{日期}.csv` |
| 搜索评论（可选） | `美食_comments_2026-07-07.csv` | 开启评论爬取时才有 |
| 博主 | `爱吃的胖泽_2026-07-08.csv` | `{昵称}_{日期}.csv` |

同一关键词/博主重复爬取时，**同文件追加写入，按 `note_id` 去重**。

---

## 3. 快速开始（5 分钟）

### 3.1 创建客户端

```python
from sdk import XhsDataClient

# 本地模式（推荐：与爬虫同机部署）
client = XhsDataClient.local(data_dir="data/xhs/csv")

# 远程模式（后端与爬虫服务分离）
client = XhsDataClient.remote("http://127.0.0.1:8080")
```

远程模式需先启动 API：

```bash
uv run uvicorn api.main:app --host 0.0.0.0 --port 8080
```

### 3.2 读关键词搜索数据

```python
from sdk import XhsDataClient

client = XhsDataClient.local()

# 按关键词加载最新 CSV
dataset = client.search.load(keyword="美食")

print(dataset.source_file)   # 实际读取的文件路径
print(dataset.keywords)      # ['美食']
print(dataset.note_count)    # 20

for note in dataset.notes:
    print(note.note_id, note.title, note.liked_count)
```

### 3.3 读博主数据

```python
dataset = client.creator.load(nickname="爱吃的胖泽")

if dataset.profile:
    print(dataset.profile.nickname, dataset.profile.fans)

print(dataset.note_count)  # 笔记条数
```

### 3.4 转成入库结构

```python
search_records = client.search.to_db_records(
    client.search.load(keyword="美食")
)
creator_records = client.creator.to_db_records(
    client.creator.load(nickname="爱吃的胖泽")
)

# search_records["notes"]     → list[dict]，每条含全部字段
# creator_records["creator"]  → dict 或 None
# creator_records["notes"]    → list[dict]
```

完整可运行示例：

```bash
uv run python examples/xhs_sdk_integration.py
```

---

## 4. 两种部署模式怎么选？

| 场景 | 模式 | 写法 |
|------|------|------|
| 后端与爬虫在同一台机器 / 同一容器 / 共享 `data/` 目录 | **local** | `XhsDataClient.local()` |
| 后端在独立服务，通过 HTTP 访问爬虫/API 机器 | **remote** | `XhsDataClient.remote("http://host:8080")` |

两种模式 **返回字段完全一致**，切换时通常只需改客户端创建方式。

```python
# 推荐：用 context manager 自动关闭远程连接
with XhsDataClient.remote("http://127.0.0.1:8080") as client:
    dataset = client.search.load(keyword="旅游")
```

---

## 5. API 参考

### 5.1 客户端

| 方法 | 说明 |
|------|------|
| `XhsDataClient.local(data_dir="data/xhs/csv")` | 本地读 CSV |
| `XhsDataClient.remote(base_url, timeout=30)` | 远程调 HTTP |
| `client.close()` | 关闭远程 HTTP 连接 |

### 5.2 关键词搜索 `client.search`

| 方法 | 返回 | 用途 |
|------|------|------|
| `load(keyword=None, file_path=None, with_comments=False)` | `XhsSearchDataset` | **主入口**，拿全量结构化数据 |
| `export(keyword=None, ...)` | `dict` | 与 HTTP `/api/data/search-export` 相同 |
| `summary(keyword=None)` | `dict` | 只要统计，不要明细 |
| `list_available()` | `list[dict]` | 扫描目录下所有搜索 CSV |
| `to_db_records(dataset)` | `dict` | 转入库结构 |

**`load()` 参数说明：**

- `keyword`：如 `"美食"`，自动匹配 `美食_*.csv` 中最新文件
- `file_path`：指定具体 CSV（相对 `data/` 或绝对路径）
- `with_comments=True`：同时加载 `{关键词}_comments_{日期}.csv`

### 5.3 博主数据 `client.creator`

| 方法 | 返回 | 用途 |
|------|------|------|
| `load(nickname=None, file_path=None)` | `XhsCreatorDataset` | **主入口** |
| `export(nickname=None, ...)` | `dict` | 与 HTTP `/api/data/creator-export` 相同 |
| `summary(nickname=None)` | `dict` | 只要统计 |
| `list_available()` | `list[dict]` | 已爬取的博主列表 |
| `to_db_records(dataset)` | `dict` | 转入库结构 |

### 5.4 文件工具 `client.files`（辅助）

| 方法 | 说明 |
|------|------|
| `list(platform="xhs", file_type="csv")` | 列出数据文件 |
| `preview(file_path, limit=100)` | 预览 CSV/JSON 前几行 |
| `stats()` | 数据目录统计 |
| `health()` | 健康检查（remote 调 API，local 固定返回 ok） |

---

## 6. 常见业务场景

### 6.1 定时任务：扫描新数据并入库

```python
from sdk import XhsDataClient

client = XhsDataClient.local()

for item in client.search.list_available():
    keyword = item["keywords"][0]
    records = client.search.to_db_records(
        client.search.load(keyword=keyword)
    )
    for note in records["notes"]:
        db.upsert("xhs_search_notes", key="note_id", data=note)
```

### 6.2 后台列表页：展示已爬取的关键词 / 博主

```python
searches = client.search.list_available()
# [{"file_name": "美食_2026-07-07.csv", "keywords": ["美食"], "note_count": 20, ...}]

creators = client.creator.list_available()
# [{"nickname": "爱吃的胖泽", "fans": "23395", "note_count": 60, ...}]
```

### 6.3 对外 REST 接口：复用 export 结构

```python
from fastapi import APIRouter
from sdk import XhsDataClient

router = APIRouter()
client = XhsDataClient.local()

@router.get("/internal/xhs/search")
def get_search_notes(keyword: str):
    return client.search.export(keyword=keyword)
```

### 6.4 只要数量，不要明细

```python
summary = client.search.summary(keyword="美食")
# {"note_count": 20, "keywords": ["美食"], "notes_per_keyword": {"美食": 20}, ...}
```

### 6.5 指定历史文件（非最新）

```python
dataset = client.search.load(
    file_path="data/xhs/csv/美食_2026-07-07.csv"
)
```

### 6.6 加载评论

```python
dataset = client.search.load(keyword="美食", with_comments=True)
print(len(dataset.comments))

for comment in dataset.comments:
    if comment.note_id == some_note_id:
        print(comment.content)
```

---

## 7. 返回数据结构

### 7.1 哪些方法有全字段？

| 方法 | 全字段？ | 说明 |
|------|---------|------|
| `load()` | ✅ | 返回 Pydantic 模型，属性即 CSV 列 |
| `export()` | ✅ | JSON 兼容 dict |
| `to_db_records()` | ✅ | 入库用 dict |
| `summary()` | ❌ | 仅统计信息 |

**需要明细用 `load()` / `export()` / `to_db_records()`；只要数量用 `summary()`。**

### 7.2 搜索笔记字段（`XhsSearchNote`）

```python
note = client.search.load(keyword="美食").notes[0]
note.model_dump()  # 单条全字段 dict
```

| 字段 | 说明 |
|------|------|
| `note_id` | 笔记 ID，**入库主键推荐** |
| `type` | `normal` / `video` |
| `title` / `desc` | 标题 / 正文 |
| `video_url` | 视频地址 |
| `time` / `last_update_time` | 时间戳（毫秒） |
| `creator_hash` | 作者 `user_id` |
| `nickname` | 作者完整昵称 |
| `liked_count` / `collected_count` / `comment_count` / `share_count` | 互动数据（可能是 `"10万+"` 中文格式） |
| `image_list` / `tag_list` | 逗号分隔的 URL / 标签 |
| `note_url` | 笔记链接 |
| `source_keyword` | 搜索关键词，如 `美食` |
| `xsec_token` | 访问令牌 |
| `last_modify_ts` | 爬虫写入时间 |

辅助方法：`note.image_urls()`、`note.topic_tags()` 可把逗号分隔字符串拆成列表。

### 7.3 评论字段（`XhsSearchComment`，需 `with_comments=True`）

| 字段 | 说明 |
|------|------|
| `comment_id` | 评论 ID，入库主键 |
| `note_id` | 所属笔记 |
| `content` | 评论正文 |
| `creator_hash` / `nickname` | 评论者 ID / 昵称 |
| `like_count` / `sub_comment_count` | 点赞 / 子评论数 |
| `parent_comment_id` | 父评论 ID，顶级为空 |

### 7.4 博主简介（`XhsCreatorProfile`）

| 字段 | 说明 |
|------|------|
| `user_id` | 博主 ID |
| `nickname` | 昵称 |
| `gender` / `avatar` / `desc` / `ip_location` | 基本信息 |
| `follows` / `fans` / `interaction` | 关注 / 粉丝 / 获赞收藏 |
| `tag_list` | 博主标签（JSON 字符串） |

博主笔记 `dataset.notes[]` 字段与搜索笔记基本相同，`source_keyword` 通常为空。

### 7.5 `to_db_records()` 结构

**搜索：**

```python
{
    "keywords": ["美食"],
    "notes": [{ /* 全字段 */ }, ...],
    "comments": [{ /* 全字段 */ }, ...],
    "grouped_notes": {"美食": [{ /* 全字段 */ }, ...]},
    "meta": {"source_file": "...", "note_count": 20, ...}
}
```

**博主：**

```python
{
    "creator": { /* 全字段，可能为 null */ },
    "notes": [{ /* 全字段 */ }, ...],
    "meta": {"source_file": "...", "note_count": 60}
}
```

---

## 8. 异常处理

```python
from sdk import XhsDataClient, NotFoundError, ApiError, SdkError

client = XhsDataClient.local()

try:
    dataset = client.search.load(keyword="不存在的关键词")
except FileNotFoundError:
    # 本地：目录下没有匹配的 CSV
    ...
except NotFoundError:
    # 远程 preview 等：文件不存在
    ...
except ApiError as e:
    # 远程：HTTP 4xx/5xx
    print(e.status_code, e.detail)
except SdkError:
    # 其他 SDK 错误
    ...
```

---

## 9. 注意事项

1. **SDK 不跑爬虫**：没有 CSV 时会抛 `FileNotFoundError`，需先让爬虫生成数据。
2. **`keyword` 与文件名对应**：`load(keyword="美食")` 会找 `美食_*.csv` 最新一份，不会读 `旅游_*.csv`。
3. **中文路径/参数**：远程模式 SDK 内部已处理 URL 编码；手写 HTTP 时请用 `params=` 传参。
4. **点赞数排序**：`liked_count` 可能是 `"7.5万"`，数值比较需自行解析。
5. **数据实时性**：爬虫追加写入 CSV 后，下次 `load()` 即可读到，**无需重启**后端或 API。
6. **当前仅小红书**：抖音等平台尚未纳入 SDK，请勿对 `XhsDataClient` 期望跨平台。

---

## 10. 与 HTTP API 的关系

SDK remote 模式与 FastAPI 路由一一对应：

| SDK | HTTP |
|-----|------|
| `client.search.export(keyword=...)` | `GET /api/data/search-export?keyword=...` |
| `client.search.summary(keyword=...)` | `GET /api/data/search-export/summary?keyword=...` |
| `client.creator.export(nickname=...)` | `GET /api/data/creator-export?nickname=...` |
| `client.files.list()` | `GET /api/data/files` |
| `client.files.health()` | `GET /api/health` |

若团队不使用 Python SDK，也可直接调 HTTP，响应结构与 `export()` 相同。详见 [xhs_data_api.md](./xhs_data_api.md)。

---

## 11. 相关文件

| 路径 | 说明 |
|------|------|
| `sdk/` | SDK 源码 |
| `docs/xhs_sdk_live_crawl.md` | **实时爬取** `keyword_ex` / `creator_ex` 技术文档 |
| `examples/xhs_sdk_integration.py` | 可运行示例（读 CSV 模式） |
| `docs/xhs_data_api.md` | HTTP API + 字段详细说明 |
| `data/xhs/csv/` | 默认 CSV 数据目录 |

---

## 12. 一页速查

```python
from sdk import XhsDataClient

client = XhsDataClient.local()

# 搜索
ds = client.search.load(keyword="美食")
records = client.search.to_db_records(ds)

# 博主
ds = client.creator.load(nickname="爱吃的胖泽")
records = client.creator.to_db_records(ds)

# 列表
client.search.list_available()
client.creator.list_available()

# 远程
with XhsDataClient.remote("http://127.0.0.1:8080") as client:
    ds = client.search.load(keyword="旅游")
```
