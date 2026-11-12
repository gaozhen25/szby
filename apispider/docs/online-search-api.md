# 在线搜索 API

## 接口

- 方法：`POST`
- 路径：`/api/v1/online-search`
- 鉴权：StarX Bearer Token
- 当前供应商：豆包搜索

请求示例：

```json
{
  "query": "推荐几个抖音上真实存在的美妆博主，只返回主页链接",
  "searchType": "web",
  "count": 10,
  "filter": {
    "needContent": true,
    "needUrl": false,
    "sites": "",
    "blockHosts": "",
    "authInfoLevel": 0
  },
  "needSummary": true,
  "timeRange": "",
  "queryControl": {
    "queryRewrite": false
  }
}
```

接口会透传豆包搜索成功响应中的 JSON 对象，便于调用方使用供应商提供的完整结果字段。供应商配置缺失时返回 `503`，网络、上游 HTTP 或响应格式异常时返回 `502`。

## 配置

真实密钥只应配置在 `starx-backend/.env` 或部署环境的密钥管理系统中：

```dotenv
STARX_DOUBAO_SEARCH_API_URL=https://open.feedcoopapi.com/search_api/web_search
STARX_DOUBAO_SEARCH_API_KEY=
STARX_DOUBAO_SEARCH_TIMEOUT=30
```

`OnlineSearchService` 依赖统一的供应商协议，后续接入新的在线搜索供应商时，只需新增适配器并在服务装配处切换，无需修改 API 请求模型。
