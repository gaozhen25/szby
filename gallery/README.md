# Gallery

`gallery.bytech.tech` — 抖音 / 小红书分享链接解析。前后端都在这个目录。

不登录 DataTool，也不登录抖音或小红书。做法和本机 `~/yt-dlp` 一样：

- **抖音**：短链解析出作品 ID → 读 `iesdouyin.com/share/{video|note|slides}/{id}` 的公开 JSON。图文走图片列表（不用带水印的 `tplv-dy-water`）。视频只用 `watermark=0`。不启动浏览器。
- **小红书**：短链解析笔记 ID → 读公开页 `window.__INITIAL_STATE__`。图片用 `fileId` 原文件（`sns-img-qc.xhscdn.com`），不带 `!h5_1080jpg`。视频用 `originVideoKey`。

## 本地运行

```bash
cd /Users/gzbytech.tech/gallery
bash run.sh
```

打开 http://127.0.0.1:8790/

## 域名

把 `gallery.bytech.tech` 指到这台机器，然后：

```bash
caddy run --config /Users/gzbytech.tech/gallery/Caddyfile
```

应用监听 `127.0.0.1:8790`，Caddy 在本机反代到它。后台在 `/admin`。

## 接口

网页用的单条解析不入库：

`POST /api/parse` body `{"text":"<分享文案或链接>"}`  
`GET /api/media?url=` 代拉允许的 CDN（下载按钮用）

给其他服务调用的两个接口要带 API Key，请求头任选其一：

```
Authorization: Bearer <key>
X-Api-Key: <key>
```

Key 放在环境变量 `GALLERY_API_KEY`。没设置时，第一次启动写到 `data/api_key`（权限 600）。交互式文档在 `/docs`。

### 批量解析并入库

`POST /api/v1/parse`

```bash
curl -s https://gallery.bytech.tech/api/v1/parse \
  -H "Authorization: Bearer $GALLERY_API_KEY" \
  -H "content-type: application/json" \
  -d '{"texts":["https://v.douyin.com/…","http://xhslink.com/…"]}'
```

也接受单个字段 `text`。一段里有多行、且多行都带链接时，会拆成多条。一次最多 20 条。同一作品（平台 + 作品 ID）再次解析会更新原记录，不另存一条；后来写上的 `note` 和 `labels` 会保留。

图片和视频上传到阿里云 OSS 的官方节点 `{bucket}.oss-{region}.aliyuncs.com`，配置写在项目根目录的 `.env`（`bash run.sh` 会读它）。桶保持私有，文件长期保存在 OSS。接口和后台给出的地址是本站固定路径，不会过期，打开时由服务器用 AccessKey 去读。目录索引仍在本机 `data/library.sqlite`。

只要元数据、不上传文件时传 `"download": false`。链接没变时不重复上传；要强制重传传 `"refresh_files": true`。单文件上限默认 512MB，用 `GALLERY_MAX_FILE_BYTES` 调整。

失败的条目在 `results` 里单独返回，不会让整批变成一个错误。

### 素材库

库里的一条是一张图或一个视频，不把整篇作品当成一条。作品只作为来源留着：文案、原始标签、公开页里能读到的评论。调用方用 `category` 和 `labels` 给素材分类，再拿 `href` 做二次处理。

`GET /api/v1/library?q=&platform=douyin|xhs&type=image|video&category=&tag=&source_id=&limit=20&offset=0`  
`GET /api/v1/library/{id}`  
`GET /api/v1/library/{id}/file` 读取已经保存在 OSS 的这一条文件，地址长期有效，同样要带 API Key  
`PATCH /api/v1/library/{id}` body `{"category":"人物","note":"留给后期","labels":["已选"]}`  
`DELETE /api/v1/library/{id}` 只删这一条素材

列表和详情里的 `href` 就是上面的文件地址。`source.content`、`source.tags`、`source.comments` 是原始作品上的信息。`category` 和 `labels` 是调用方自己标的。公开页如果没有评论正文，`source.comments` 为空，`source.comment_count` 仍可能有数字。
