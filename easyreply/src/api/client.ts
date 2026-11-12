// ============================================================
// HTTP 客户端重新导出
// 所有 HTTP 请求工具统一从这里导出
// ============================================================

export {
  default as api,
  get,
  post,
  put,
  patch,
  del,
  upload,
  ApiError,
  getAuthApiBaseUrl,
} from '@/lib/http';

export type {
  HttpMethod,
  RequestConfig,
} from '@/lib/http';
