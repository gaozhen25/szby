# 小红书同进程直传 Dict 接入文档

> **方案说明**：在同一 Python 进程内调用 `keyword_ex` / `creator_ex`，爬取完成后 **直接拿到内存中的标准 API dict**，交给后端业务逻辑处理。  
> **不读 JSON、不调用 `XhsBackendClient.archive.local()`、不要求 FastAPI 中转。**

相关文档：[xhs_sdk_live_crawl.md](./xhs_sdk_live_crawl.md)（含 JSON 落盘、HTTP `live()` 等其它接入方式）

---

## 1. 代码里有没有？

**有，且已是当前 SDK 的主路径。**

| 能力 | 入口 | 源码 |
|------|------|------|
| 关键词搜索 → dict | `keyword_ex()` / `keyword_ex_async()` | `sdk/extractor.py` |
| 博主爬取 → dict | `creator_ex()` / `creator_ex_async()` | `sdk/extractor.py` |
| 爬取编排 + 内存组装 | `run_keyword_search()` / `run_creator_crawl()` | `services/crawler_runner.py` |
| dict 结构封装 | `XhsSearchService.to_api_response()` / `XhsCreatorService.to_api_response()` | `services/xhs_*_service.py` |
| CLI 快捷命令 | `./mc search` / `./mc creator` | `mc` → `sdk_cli.py`（内部同样走 SDK） |

单元测试：`tests/test_sdk_extractor_api_dict.py`（断言返回值为标准 dict）。

FastAPI 实时接口 `POST /api/data/crawl/search` 内部也是 `await sdk.keyword_ex_async(...)`，与本方案 **同一份 dict**，只是多了一层 HTTP；本方案省略 HTTP，直接在进程内拿返回值。

---

## 2. 整体流程

```
你的后端 / 脚本
    │
    ▼
keyword_ex("xhs", "猫咪")          ← 同步入口（无 running event loop）
  或 await keyword_ex_async(...)    ← async 入口（FastAPI / asyncio 内）
    │
    ▼
services/crawler_runner.py
    ├─ 覆盖 config：SAVE_DATA_OPTION=memory
    ├─ 启动 XiaoHongShuCrawler（CDP 浏览器）
    ├─ 数据写入 memory_collector
    ├─ 组装 XhsSearchDataset
    └─ to_api_response() → dict
    │
    ├─► return dict  ──────────────► 你的 ingest / 入库 / API 响应（本方案用这个）
    │
    └─► export_*_response() 写 JSON  （副作用，可选忽略）
            data/xhs/json/{关键词}_{日期}.json
```

**核心原则**：返回值 `dict` 即权威数据源；JSON 文件仅为备份，后端 **不必** 再读盘。

---

## 3. 快速上手

### 3.1 环境

```bash
cd /path/to/MediaCrawler
uv sync
```

- 本机需安装 Chrome（默认 CDP 模式，`config/base_config.py` 中 `ENABLE_CDP_MODE = True`）
- 首次运行需浏览器扫码登录；登录态见 `browser_data/`

### 3.2 关键词搜索（同步）

适用于普通脚本、Celery 同步任务、Django 管理命令等 **非 async** 上下文：

```python
from sdk import keyword_ex

result = keyword_ex(
    "xhs",
    "猫咪",
    max_notes_count=20,
    enable_comments=False,
    login_type="qrcode",
)

assert result["code"] == 0
summary = result["data"]["summary"]
notes = result["data"]["notes"]

print(summary["note_count"], notes[0]["title"])
```

### 3.3 关键词搜索（async）

适用于 FastAPI、`asyncio` 应用：

```python
from sdk import keyword_ex_async

async def fetch_notes(keyword: str) -> dict:
    result = await keyword_ex_async(
        "xhs",
        keyword,
        max_notes_count=20,
    )
    return result
```

> **注意**：在已有 event loop 中调用同步版 `keyword_ex()` 会抛出 `SdkError`，必须改用 `keyword_ex_async()`。

### 3.4 博主爬取

```python
from sdk import creator_ex

result = creator_ex(
    "xhs",
    "5aa2b1c8e8ac2b2b0f0130fe",  # user_id
    max_notes_count=20,
)

profile = result["data"]["profile"]
notes = result["data"]["notes"]
```

也支持带 `xsec_token` 的主页 URL（需引号包裹）：

```python
result = creator_ex(
    "xhs",
    "https://www.xiaohongshu.com/user/profile/xxx?xsec_token=yyy&xsec_source=pc_search",
)
```

---

## 4. 与后端业务对接

### 4.1 同进程直调（推荐本方案）

```python
from sdk import keyword_ex


def ingest_xhs_search(keyword: str) -> int:
    """爬取并入库，全程不读 JSON。"""
    result = keyword_ex("xhs", keyword, max_notes_count=20)

    if result["code"] != 0:
        raise RuntimeError(result.get("message", "crawl failed"))

    count = 0
    for note in result["data"]["notes"]:
        save_note_to_db(note)  # 自行实现
        count += 1
    return count
```

### 4.2 嵌入 FastAPI（进程内，非 live HTTP）

```python
from fastapi import FastAPI, HTTPException
from sdk import keyword_ex_async

app = FastAPI()


@app.post("/internal/xhs/search")
async def search_and_return(keyword: str, max_notes: int = 20):
    try:
        result = await keyword_ex_async(
            "xhs",
            keyword,
            max_notes_count=max_notes,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if result["code"] != 0:
        raise HTTPException(status_code=502, detail=result.get("message"))

    # 可直接 return dict 给调用方，或在此入库
    await save_notes(result["data"]["notes"])
    return result
```

与 `api/routers/live_crawl.py` 的区别：上面是 **你自己写的路由 + 直接调 SDK**；`live_crawl` 是项目自带的 `/api/data/crawl/search`，供 `XhsBackendClient.live()` 远程调用。两者拿到的 **dict 结构相同**。

### 4.3 拆层：爬虫层 + 纯后端层（同机）

即使在同一台机器，也可以拆两个 Python 模块，仍 **不读 JSON**：

```python
# crawler_bridge.py — 唯一允许 import sdk 爬虫入口的模块
from sdk import keyword_ex

def crawl_search(keyword: str) -> dict:
    return keyword_ex("xhs", keyword, max_notes_count=20)


# backend_service.py — 只处理 dict，无浏览器依赖
def handle_search_result(result: dict) -> None:
    for note in result["data"]["notes"]:
        ...
```

`backend_service.py` 不要 import `keyword_ex`，由 `crawler_bridge` 把 dict 传进来即可。

---

## 5. 标准 Dict 结构

### 5.1 关键词搜索

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "keywords": ["猫咪"],
    "notes": [
      {
        "note_id": "67a88fde000000002602d57e",
        "type": "video",
        "title": "...",
        "desc": "...",
        "video_url": "...",
        "time": "1739100126000",
        "creator_hash": "...",
        "nickname": "...",
        "liked_count": "10万+",
        "collected_count": "3.2万",
        "comment_count": "1.5万",
        "share_count": "5.2万",
        "image_list": "...",
        "tag_list": "...",
        "note_url": "https://www.xiaohongshu.com/explore/...",
        "source_keyword": "猫咪",
        "xsec_token": "..."
      }
    ],
    "comments": [],
    "grouped_notes": {
      "猫咪": [ "... 与 notes 相同结构的 note 对象 ..." ]
    },
    "summary": {
      "keywords": ["猫咪"],
      "note_count": 20,
      "comment_count": 0,
      "source_file": "data/xhs/json/猫咪_2026-07-13.json"
    }
  }
}
```

`summary.source_file` 表示落盘路径（若有写 JSON）；**入库可忽略该字段**。

### 5.2 博主爬取

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "profile": {
      "user_id": "...",
      "nickname": "...",
      "desc": "...",
      "fans": "...",
      "follows": "...",
      "interaction": "..."
    },
    "notes": [ "..." ],
    "summary": {
      "note_count": 20,
      "source_file": "data/xhs/json/{昵称}_{日期}.json"
    }
  }
}
```

字段定义与 Pydantic 模型一致，见 `services/xhs_search_dataset.py`、`services/xhs_creator_dataset.py`。

---

## 6. 参数说明

### `keyword_ex` / `keyword_ex_async`

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `platform` | str | — | 目前仅 `"xhs"` |
| `keyword` | str | — | 搜索关键词 |
| `login_type` | str | `"qrcode"` | `qrcode` / `phone` / `cookie` |
| `max_notes_count` | int \| None | `None` | 最多爬取条数；不传则用 config 默认 |
| `enable_comments` | bool | `False` | 是否爬评论 |
| `enable_sub_comments` | bool | `False` | 是否爬二级评论 |
| `headless` | bool \| None | `None` | 是否无头；`None` 用 config |
| `cookies` | str | `""` | `login_type=cookie` 时使用 |
| `start_page` | int | `1` | 起始页（仅 search） |

### `creator_ex` / `creator_ex_async`

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `creator_id` | str | — | 24 位 user_id 或主页 URL |
| 其余 | — | — | 同 keyword，无 `start_page` |

---

## 7. 与其它接入方式对比

| 方式 | 是否读 JSON | 是否要浏览器 | 典型场景 |
|------|-------------|--------------|----------|
| **本方案：`keyword_ex` 返回值** | 否 | 是（调用方进程） | 同机脚本、自建 FastAPI、爬虫+后端一体 |
| `XhsBackendClient.archive.local()` | 是 | 否 | 纯后端、爬虫已跑完 |
| `XhsBackendClient.live()` | 否 | 是（爬虫机 API 进程） | 后端与爬虫分机部署 |
| `./mc search` | 否（CLI 只打印 summary） | 是 | 命令行手动爬取；要写后端需再用 Python 调 `keyword_ex` |

---

## 8. 异常与注意事项

| 现象 | 原因 | 处理 |
|------|------|------|
| `SdkError: keyword_ex() 不能在 async 上下文...` | 在 async 里调了同步版 | 改用 `await keyword_ex_async()` |
| `ValueError: 暂不支持的平台` | platform 非 xhs | 目前仅 xhs |
| 浏览器反复要求扫码 | 登录态未保存 | 见 `browser_data/`、`cdp_xhs_storage_state.json` |
| 爬取慢 / 超时 | 需启动 Chrome + 登录 | 首次 1～2 分钟正常；生产环境可加长外层 timeout |
| 磁盘上仍有 JSON | `crawler_runner` 落盘副作用 | 可忽略；当前 **无** `write_json=False` 开关 |

爬取过程中数据先进入 `store/memory_collector.py`（`SAVE_DATA_OPTION=memory`），再组装为 dict；**不依赖 CSV**。

---

## 9. 源码索引

| 文件 | 职责 |
|------|------|
| `sdk/__init__.py` | 导出 `keyword_ex`、`creator_ex` |
| `sdk/extractor.py` | SDK 类与 sync/async 入口 |
| `services/crawler_runner.py` | 爬取编排、return dict、顺带写 JSON |
| `services/xhs_search_service.py` | 搜索 dict 结构 `to_api_response` |
| `services/xhs_creator_service.py` | 博主 dict 结构 `to_api_response` |
| `store/memory_collector.py` | 单次爬取内存容器 |
| `services/sdk_json_export.py` | JSON 落盘（本方案可忽略） |
| `tests/test_sdk_extractor_api_dict.py` | dict 返回值测试 |

---

## 10. 最小可运行示例

在项目根目录保存为 `scripts/direct_dict_demo.py`（或任意路径，需在项目根执行）：

```python
#!/usr/bin/env python3
"""同进程直传 dict 演示 — 不读 JSON。"""
from sdk import keyword_ex


def main() -> None:
    result = keyword_ex("xhs", "猫咪", max_notes_count=5)

    if result["code"] != 0:
        raise SystemExit(result.get("message", "failed"))

    data = result["data"]
    print("note_count:", data["summary"]["note_count"])
    for i, note in enumerate(data["notes"][:3], 1):
        print(f"  [{i}] {note['title'][:40]}  👍 {note['liked_count']}")

    # 此处将 result 传给后端即可，例如：
    # backend.ingest(result)


if __name__ == "__main__":
    main()
```

运行：

```bash
uv run python scripts/direct_dict_demo.py
```

---

## 11. 总结

- **第一种方案（同进程直传 dict）已在代码中实现**，入口为 `keyword_ex` / `creator_ex`。
- 调用方使用 **函数返回值** 即可，无需 `XhsBackendClient`，无需读 `data/xhs/json/`。
- JSON 写入是附加行为，用于备份与 `archive.local()` 场景；与本方案并行存在，互不依赖。
