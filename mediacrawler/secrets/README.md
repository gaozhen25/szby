# Cookie 文件（勿提交真实 Cookie）

推荐合并池：`secrets/cookies.json`

```json
{
  "xhs": ["web_session=...; a1=..."],
  "dy": ["sessionid=..."],
  "ks": []
}
```

| 文件 | 用途 |
|------|------|
| `cookies.json` | 小红书 + 抖音（+ 可选快手）合并池 |
| `dyhot.cookies.json` | 热点宝（仍单独导出） |
| `*.cookies.json` | 单平台兼容文件 |

多账号：同一平台数组可放多条 Cookie 串。

## 扫码导出（小红书 + 抖音一次跑完）

```bash
uv run python scripts/export_cookies.py
```

依次在浏览器完成小红书、抖音（已登录则跳过扫码），写入 `secrets/cookies.json`：

```json
{
  "xhs": ["web_session=..."],
  "dy": ["sessionid=..."],
  "ks": []
}
```

仅此一个导出脚本：`scripts/export_cookies.py`。

## Cookie 登录运行（Playwright 无头浏览器，非 CDP）

```bash
uv run python scripts/run_with_cookies.py xhs --keywords 猫咪 --max-notes 20
uv run python scripts/run_with_cookies.py dyhot --max-notes 20
```

扫码导出仍用有头本地 CDP；Cookie 爬取走 Playwright Chromium 无头（`--enable_cdp false --headless true`）。

真实 Cookie 已被 gitignore，只提交 `*.example` 与本说明。
