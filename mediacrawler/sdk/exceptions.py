# -*- coding: utf-8 -*-
"""SDK 异常定义。"""

from __future__ import annotations


class SdkError(Exception):
    """SDK 基础异常。"""


class NotFoundError(SdkError):
    """数据文件或资源不存在。"""


class ApiError(SdkError):
    """远程 API 调用失败。"""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"HTTP {status_code}: {detail}")
