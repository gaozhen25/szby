// ============================================================
// API 公共类型定义
// ============================================================

import type { ApiError as _ApiError } from '@/lib/http';

/** API 统一响应结构（后端标准格式） */
export interface ApiResponse<T = unknown> {
  code: number;
  message: string;
  data: T;
}

/** 分页参数 */
export interface PaginationParams {
  page?: number;
  page_size?: number;
}

/** 分页响应 */
export interface PaginatedData<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

// 重新导出 ApiError 方便外部引用
export type ApiError = _ApiError;
