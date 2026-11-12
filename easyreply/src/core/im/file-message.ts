/** contentType=105 文件消息 content（与下行 file 结构对齐） */
export type FileMessageContent = {
  fileName: string;
  fileSize: number;
  sourceUrl: string;
  uuid: string;
};

function newUUID(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

/** 构造 contentType=105 的文件消息 content（先上传文件，再带 sourceUrl 发送） */
export function buildFileMessageContent(params: {
  fileName: string;
  fileSize: number;
  sourceUrl: string;
  objectKey?: string;
  uuid?: string;
}): FileMessageContent {
  return {
    fileName: params.fileName,
    fileSize: Math.max(0, Math.round(params.fileSize)),
    sourceUrl: params.objectKey || params.sourceUrl,
    uuid: params.uuid || newUUID(),
  };
}

export function formatFileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '';
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(bytes < 10 * 1024 * 1024 ? 1 : 0)}MB`;
}
