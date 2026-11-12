# 小红书爬取数据 API 接口文档

> 面向后端同事的接入说明。  
> 数据源为爬虫生成的 CSV 文件，API **每次请求实时读取磁盘**，无缓存、无数据库。

---

## 1. 整体架构

```
爬虫 (main.py)
    │
    ▼ 写入 CSV（追加模式，不覆盖）
data/xhs/csv/
    ├── 旅游_2026-07-07.csv          ← 关键词搜索
    ├── 旅游_comments_2026-07-07.csv ← 评论（可选）
    └── Charon💕_2026-07-07.csv       ← 博主爬取
    │
    ▼ 每次请求读取
FastAPI (api/routers/data.py)
    │
    ▼ 解析为 JSON
后端服务 / 前端
```

**核心原则：CSV 是唯一数据源。CSV 里有什么，API 就返回什么。**

- 爬虫再次运行、同名文件存在时：**追加新数据**，已存在的 `note_id` / `comment_id` 不重复写入
- API 无 WebSocket 推送，需客户端**主动轮询或刷新**

---

## 2. 服务启动

```bash
cd MediaCrawler
uv run uvicorn api.main:app --host 127.0.0.1 --port 8080
```

| 地址 | 说明 |
|------|------|
| http://127.0.0.1:8080/docs | Swagger 交互文档 |
| http://127.0.0.1:8080/api/health | 健康检查 |

健康检查响应：

```json
{"status": "ok"}
```

---

## 3. CSV 文件命名规则

### 3.1 关键词搜索（`--type search`）

| 类型 | 文件名格式 | 示例 |
|------|-----------|------|
| 笔记 | `{关键词}_{日期}.csv` | `旅游_2026-07-07.csv` |
| 评论 | `{关键词}_comments_{日期}.csv` | `旅游_comments_2026-07-07.csv` |

笔记 CSV 首列是 `note_id`，每行一条笔记，`source_keyword` 字段标记所属关键词。

### 3.2 博主爬取（`--type creator`）

| 类型 | 文件名格式 | 示例 |
|------|-----------|------|
| 博主+笔记合并 | `{昵称}_{日期}.csv` | `Charon💕_2026-07-07.csv` |

合并 CSV 结构：

| 行号 | record_type | 内容 |
|------|-------------|------|
| 第 1 行 | `profile` | 博主简介（粉丝数、IP 属地等） |
| 第 2+ 行 | `note` | 博主发布的笔记 |

---

## 4. 接口一览

所有数据接口前缀：`/api/data`

### 4.1 通用文件接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/data/files` | 列出所有数据文件 |
| GET | `/api/data/files/{file_path}` | 预览文件内容（CSV 转 JSON 行） |
| GET | `/api/data/download/{file_path}` | 下载原始文件 |
| GET | `/api/data/stats` | 文件数量、大小统计 |

**列出文件示例：**

```
GET /api/data/files?platform=xhs&file_type=csv
```

**预览原始 CSV（与文件列完全一致）：**

```
GET /api/data/files/xhs/csv/旅游_2026-07-07.csv?preview=true&limit=100
```

响应：

```json
{
  "data": [
    {"note_id": "6954bd7f...", "title": "人生日落", "source_keyword": "旅游", ...}
  ],
  "total": 20
}
```

---

### 4.2 关键词搜索接口（推荐后端使用）

#### GET `/api/data/search-export`

将关键词搜索 CSV 解析为结构化 JSON。

**Query 参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `keyword` | string | 否 | 按关键词过滤，如 `旅游`、`美食` |
| `file_path` | string | 否 | 指定文件，相对 `data/` 路径，如 `xhs/csv/旅游_2026-07-07.csv` |
| `platform` | string | 否 | 默认 `xhs` |
| `with_comments` | bool | 否 | 是否加载评论，默认 `false` |

`keyword` 与 `file_path` 二选一。都不传时，取目录下**修改时间最新**的搜索 CSV。

**请求示例：**

```bash
curl -G "http://127.0.0.1:8080/api/data/search-export" \
  --data-urlencode "keyword=旅游"
```

**响应结构：**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "keywords": ["旅游"],
    "notes": [
      {
        "note_id": "6954bd7f000000001f0076ad",
        "type": "normal",
        "title": "人生日落",
        "desc": "...",
        "video_url": "",
        "time": "1767161215000",
        "last_update_time": "1767163498000",
        "creator_hash": "ef5518f4485fc2fb",
        "nickname": "B***冉",
        "liked_count": "10万+",
        "collected_count": "2.2万",
        "comment_count": "1.1万",
        "share_count": "4.2万",
        "image_list": "http://...,http://...",
        "tag_list": "travel,在路上收藏世界",
        "last_modify_ts": "1783410704718",
        "note_url": "https://www.xiaohongshu.com/explore/...",
        "source_keyword": "旅游",
        "xsec_token": "ABxjWjF6-..."
      }
    ],
    "comments": [],
    "grouped_notes": {
      "旅游": [ /* 同上 notes 数组 */ ]
    },
    "summary": {
      "source_file": "/path/to/data/xhs/csv/旅游_2026-07-07.csv",
      "keywords": ["旅游"],
      "note_count": 20,
      "comment_count": 0,
      "notes_per_keyword": {"旅游": 20}
    }
  }
}
```

**笔记字段说明：**

| 字段 | 说明 |
|------|------|
| `note_id` | 笔记唯一 ID，入库主键推荐 |
| `source_keyword` | 搜索关键词 |
| `liked_count` / `collected_count` | 字符串格式，可能含「万」 |
| `image_list` | 逗号分隔的图片 URL |
| `tag_list` | 逗号分隔的话题标签 |
| `time` | 发布时间戳（毫秒字符串） |
| `note_url` | 笔记原始链接 |

---

#### GET `/api/data/search-export/summary`

只返回摘要，适合列表页、仪表盘。

**Query 参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `keyword` | string | 否 | 按关键词匹配最新文件 |
| `platform` | string | 否 | 默认 `xhs` |

**请求示例：**

```
GET /api/data/search-export/summary?keyword=旅游
```

**响应：**

```json
{
  "source_file": "/Users/.../data/xhs/csv/旅游_2026-07-07.csv",
  "keywords": ["旅游"],
  "note_count": 20,
  "comment_count": 0,
  "notes_per_keyword": {"旅游": 20}
}
```

---

### 4.3 博主数据接口

#### GET `/api/data/creator-export`

将博主合并 CSV 解析为结构化 JSON。

**Query 参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `nickname` | string | 否 | 博主昵称，匹配 `{昵称}_*.csv` 最新文件 |
| `file_path` | string | 否 | 指定文件，如 `xhs/csv/Charon💕_2026-07-07.csv` |
| `platform` | string | 否 | 默认 `xhs` |

**请求示例：**

```bash
curl -G "http://127.0.0.1:8080/api/data/creator-export" \
  --data-urlencode "nickname=Charon💕"
```

**响应结构（直接返回数据集，无 code 包装）：**

```json
{
  "profile": {
    "user_id": "5f3d8b2e...",
    "nickname": "Charon💕",
    "gender": "Female",
    "avatar": "https://...",
    "desc": "博主简介...",
    "ip_location": "江苏",
    "follows": "128",
    "fans": "3.2万",
    "interaction": "10万+",
    "tag_list": "",
    "last_modify_ts": "1783410704000"
  },
  "notes": [
    {
      "note_id": "abc123...",
      "type": "normal",
      "title": "笔记标题",
      "desc": "...",
      "liked_count": "1.2万",
      "note_url": "https://www.xiaohongshu.com/explore/...",
      ...
    }
  ],
  "source_file": "/path/to/data/xhs/csv/Charon💕_2026-07-07.csv",
  "note_count": 15
}
```

---

#### GET `/api/data/creator-export/summary`

**请求示例：**

```
GET /api/data/creator-export/summary?nickname=Charon💕
```

**响应：**

```json
{
  "source_file": "/path/to/Charon💕_2026-07-07.csv",
  "nickname": "Charon💕",
  "fans": "3.2万",
  "follows": "128",
  "ip_location": "江苏",
  "note_count": 15
}
```

---

## 5. 文件查找逻辑

### 关键词搜索

1. 扫描 `data/xhs/csv/*.csv`
2. 排除博主合并文件（首列是 `record_type` 的跳过）
3. 排除 `*_comments_*` 评论文件
4. 若传了 `keyword`，优先匹配 `{keyword}_{日期}.csv`
5. 多个候选时，取**修改时间最新**的文件

### 博主数据

1. 扫描 `data/xhs/csv/*.csv`
2. 排除 `creator_`、`search_`、`detail_` 开头的旧格式文件
3. 若传了 `nickname`，匹配以 `{nickname}_` 开头的文件
4. 取**修改时间最新**的文件

---

## 6. 错误码

| HTTP 状态码 | 场景 | 响应示例 |
|------------|------|---------|
| 200 | 成功 | 见上文响应结构 |
| 404 | CSV 不存在 | `{"detail": "在 .../data/xhs/csv 中未找到关键词搜索 CSV （keyword='旅游'）"}` |
| 403 | 文件路径越权 | `{"detail": "Access denied"}` |
| 500 | 解析异常 | `{"detail": "错误信息"}` |

---

## 7. 后端接入方式

### 方式 A：SDK（推荐）

统一封装本地 CSV 读取与远程 HTTP 调用，API 与业务代码共用同一套逻辑。

> **后端专用 SDK 文档**（作用说明、部署模式、场景示例、字段速查）：[xhs_sdk_guide.md](./xhs_sdk_guide.md)

```python
from sdk import XhsDataClient

# 本地模式：直接读 CSV，性能更好
client = XhsDataClient.local(data_dir="data/xhs/csv")

# 关键词搜索
dataset = client.search.load(keyword="旅游")
records = client.search.to_db_records(dataset)

# 博主数据
creator_ds = client.creator.load(nickname="Charon💕")
creator_records = client.creator.to_db_records(creator_ds)

# 远程模式：跨服务部署
with XhsDataClient.remote("http://127.0.0.1:8080") as client:
    dataset = client.search.load(keyword="旅游")
```

完整示例见 `examples/xhs_sdk_integration.py`。

### 方式 B：HTTP 调用（跨服务）

适合后端与爬虫服务分离部署，且不使用 SDK 时。

```python
import httpx

resp = httpx.get(
    "http://127.0.0.1:8080/api/data/search-export",
    params={"keyword": "旅游"},
)
data = resp.json()
notes = data["data"]["notes"]
```

### 方式 C：Python 直接 import services（同项目部署）

与 SDK 本地模式底层相同，仍可使用，但新代码建议优先使用 `sdk` 包。

```python
from services import XhsSearchService, XhsCreatorService

# 关键词搜索
search_svc = XhsSearchService(data_dir="data/xhs/csv")
dataset = search_svc.load_by_keyword("旅游")
notes = search_svc.get_notes(dataset)
db_records = search_svc.to_db_records(dataset)  # 入库格式

# 博主数据
creator_svc = XhsCreatorService(data_dir="data/xhs/csv")
dataset = creator_svc.load_by_nickname("Charon💕")
profile = creator_svc.get_profile(dataset)
notes = creator_svc.get_notes(dataset)
```

**SDK / Service 与 HTTP 接口使用同一套解析逻辑，返回数据一致。**

---

## 8. SDK 返回字段说明

> 面向后端同事：说明 `from sdk import XhsDataClient` 各方法返回什么、是否包含全字段。

### 8.1 哪些方法返回全字段？

| SDK 方法 | 是否全字段 | 说明 |
|---------|-----------|------|
| `client.search.load()` | ✅ 是 | 返回 `XhsSearchDataset`，`notes[]` 每条含 CSV 全部列 |
| `client.search.export()` | ✅ 是 | 返回 `{code, message, data}`，`data.notes[]` 全字段 |
| `client.search.to_db_records()` | ✅ 是 | `notes[]`、`grouped_notes` 内每条 dict 全字段 |
| `client.creator.load()` | ✅ 是 | 返回 `XhsCreatorDataset`，含 `profile` + `notes[]` 全字段 |
| `client.creator.export()` | ✅ 是 | 返回 `{profile, notes[], source_file, note_count}` |
| `client.creator.to_db_records()` | ✅ 是 | `{creator, notes[], meta}` 全字段 |
| `client.search.summary()` | ❌ 否 | 仅统计：`note_count`、`keywords`、`notes_per_keyword` 等 |
| `client.creator.summary()` | ❌ 否 | 仅统计：`nickname`、`fans`、`note_count` 等 |

**原则：需要明细用 `load()` / `export()` / `to_db_records()`；只要数量用 `summary()`。**

本地模式与远程模式字段一致，区别只在数据来源（读 CSV vs 调 HTTP）。

### 8.2 关键词搜索 — 笔记字段（`XhsSearchNote`）

调用示例：

```python
dataset = client.search.load(keyword="旅游")
note = dataset.notes[0]
full_dict = note.model_dump()  # 单条全字段 dict
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `note_id` | string | 笔记唯一 ID，**入库主键推荐** |
| `type` | string | 笔记类型，如 `normal` / `video` |
| `title` | string | 标题 |
| `desc` | string | 正文 |
| `video_url` | string | 视频地址（视频笔记才有） |
| `time` | string | 发布时间戳（毫秒） |
| `last_update_time` | string | 最后更新时间戳 |
| `creator_hash` | string | 作者 `user_id`（真实 ID） |
| `nickname` | string | 作者完整昵称 |
| `liked_count` | string | 点赞数，可能为 `"10万+"` |
| `collected_count` | string | 收藏数 |
| `comment_count` | string | 评论数 |
| `share_count` | string | 分享数 |
| `image_list` | string | 图片 URL，逗号分隔 |
| `tag_list` | string | 话题标签，逗号分隔 |
| `last_modify_ts` | string | 爬虫写入时间戳（毫秒） |
| `note_url` | string | 笔记网页链接 |
| `source_keyword` | string | 搜索关键词，如 `旅游` |
| `xsec_token` | string | 访问令牌 |

加载评论时（`with_comments=True`），`dataset.comments[]` 为 `XhsSearchComment`，字段如下：

| 字段 | 类型 | 说明 |
|------|------|------|
| `comment_id` | string | 评论 ID，入库主键 |
| `create_time` | string | 评论时间戳 |
| `note_id` | string | 所属笔记 ID |
| `content` | string | 评论正文 |
| `creator_hash` | string | 评论者 `user_id` |
| `nickname` | string | 评论者完整昵称 |
| `sub_comment_count` | string | 子评论数 |
| `pictures` | string | 评论图片 URL，逗号分隔 |
| `parent_comment_id` | string | 父评论 ID，顶级评论为空 |
| `last_modify_ts` | string | 爬虫写入时间戳 |
| `like_count` | string | 评论点赞数 |

### 8.3 博主数据 — 简介字段（`XhsCreatorProfile`）

```python
dataset = client.creator.load(nickname="爱吃的胖泽")
profile = dataset.profile.model_dump()
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `user_id` | string | 博主 user_id |
| `nickname` | string | 博主昵称 |
| `gender` | string | 性别，如 `Female` / `Male` |
| `avatar` | string | 头像 URL |
| `desc` | string | 个人简介 |
| `ip_location` | string | IP 属地 |
| `follows` | string | 关注数 |
| `fans` | string | 粉丝数 |
| `interaction` | string | 获赞与收藏总数 |
| `tag_list` | string | 博主标签（JSON 字符串） |
| `last_modify_ts` | string | 爬虫写入时间戳 |

### 8.4 博主数据 — 笔记字段（`XhsCreatorNote`）

`dataset.notes[]` 字段与搜索笔记基本相同（见 8.2），区别是 creator 模式下 `source_keyword` 通常为空。

额外可用辅助方法（Pydantic 模型上）：

- `note.image_urls()` → 将 `image_list` 拆成 URL 列表
- `note.topic_tags()` → 将 `tag_list` 拆成标签列表

### 8.5 `export()` 响应结构

**搜索 `client.search.export(keyword="旅游")`：**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "keywords": ["旅游"],
    "notes": [ { /* 8.2 全部字段 */ } ],
    "comments": [ { /* 8.2 评论字段，默认空 */ } ],
    "grouped_notes": { "旅游": [ /* 同上 notes */ ] },
    "summary": {
      "source_file": "...",
      "keywords": ["旅游"],
      "note_count": 20,
      "comment_count": 0,
      "notes_per_keyword": { "旅游": 20 }
    }
  }
}
```

**博主 `client.creator.export(nickname="爱吃的胖泽")`：**

```json
{
  "profile": { /* 8.3 全部字段 */ },
  "notes": [ { /* 8.4 全部字段 */ } ],
  "source_file": "...",
  "note_count": 60
}
```

### 8.6 `to_db_records()` 入库结构

**搜索：**

```python
{
  "keywords": ["旅游"],
  "notes": [ { /* 8.2 全字段 dict */ } ],
  "comments": [ { /* 评论全字段 */ } ],
  "grouped_notes": { "旅游": [ /* notes */ ] },
  "meta": { "source_file": "...", "note_count": 20, ... }
}
```

**博主：**

```python
{
  "creator": { /* 8.3 全字段 dict，可能为 null */ },
  "notes": [ { /* 8.4 全字段 dict */ } ],
  "meta": { "source_file": "...", "note_count": 60 }
}
```

### 8.7 快速验证（打印一条全字段）

```python
from sdk import XhsDataClient
import json

client = XhsDataClient.local()
dataset = client.search.load(keyword="旅游")
print(json.dumps(dataset.notes[0].model_dump(), ensure_ascii=False, indent=2))
```

与 `data/xhs/export/search_美食_latest.json` 中 `notes[]` 单条结构一致。

---

## 9. 入库参考

### 关键词笔记

```python
for note in dataset.notes:
    db.upsert(
        table="xhs_search_notes",
        key="note_id",
        data={
            "note_id": note.note_id,
            "keyword": note.source_keyword,
            "title": note.title,
            "desc": note.desc,
            "liked_count": note.liked_count,
            "note_url": note.note_url,
            # ...
        },
    )
```

### 博主数据

```python
# 1. 写入博主表
if dataset.profile:
    db.upsert(table="xhs_creators", key="user_id", data=dataset.profile.model_dump())

# 2. 写入笔记表
for note in dataset.notes:
    db.upsert(table="xhs_creator_notes", key="note_id", data=note.model_dump())
```

`search_svc.to_db_records()` / `creator_svc.to_db_records()` 已封装好入库结构，可直接使用。

---

## 10. 当前环境可用链接

基于现有 CSV 文件（`data/xhs/csv/`）：

| 数据 | 完整数据 | 摘要 |
|------|---------|------|
| 旅游（20 条） | http://127.0.0.1:8080/api/data/search-export?keyword=旅游 | http://127.0.0.1:8080/api/data/search-export/summary?keyword=旅游 |
| 美食（20 条） | http://127.0.0.1:8080/api/data/search-export?keyword=美食 | http://127.0.0.1:8080/api/data/search-export/summary?keyword=美食 |

原始 CSV 预览（列与文件完全一致）：

- http://127.0.0.1:8080/api/data/files/xhs/csv/旅游_2026-07-07.csv
- http://127.0.0.1:8080/api/data/files/xhs/csv/美食_2026-07-07.csv

---

## 11. 注意事项

1. **中文参数**：URL 中的中文需 URL 编码，建议用 `curl -G --data-urlencode` 或 httpx/requests 的 `params` 传参
2. **点赞数格式**：`liked_count` 可能是 `"10万+"` 等中文格式，数值排序需自行转换
3. **评论数据**：默认不返回评论，需加 `with_comments=true`，且评论 CSV 文件存在
4. **数据实时性**：爬虫写入 CSV 后，下次 API 请求即可读到新数据，无需重启服务
5. **去重**：同名文件重复爬取时，已存在的 `note_id` 不会重复写入 CSV

---

## 12. 相关源码

| 文件 | 职责 |
|------|------|
| `sdk/` | **小红书数据 SDK**（推荐后端接入入口） |
| `api/routers/data.py` | HTTP 路由定义（内部使用 SDK） |
| `services/xhs_search_service.py` | 关键词搜索业务层 |
| `services/xhs_search_dataset.py` | 关键词搜索数据模型 + CSV 解析 |
| `services/xhs_creator_service.py` | 博主数据业务层 |
| `services/xhs_creator_dataset.py` | 博主数据模型 + CSV 解析 |
| `store/xhs/_store_impl.py` | 爬虫写 CSV 逻辑 |
| `tools/async_file_writer.py` | CSV 追加写入 + 去重 |
