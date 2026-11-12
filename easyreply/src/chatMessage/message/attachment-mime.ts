const IMAGE_EXTS = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'heic', 'heif'];
const VIDEO_EXTS = ['mp4', 'mov', 'm4v', 'webm', 'avi', 'mkv', '3gp', 'mpeg', 'mpg', 'wmv', 'flv', 'ts'];
const TEXT_EXTS = ['txt', 'md', 'json', 'log', 'csv', 'xml', 'yaml', 'yml', 'rtf'];
const OFFICE_EXTS = ['doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx'];

export type AttachmentPreviewKind =
  | 'image'
  | 'video'
  | 'pdf'
  | 'text'
  | 'office'
  | 'file';

export function getFileExtension(fileName?: string, uri?: string): string {
  const source = (fileName || uri || '').split('?')[0].trim().toLowerCase();
  const ext = source.includes('.') ? source.split('.').pop() : '';
  return (ext || '').replace(/[^a-z0-9]/g, '');
}

export function inferMimeType(fileName?: string, uri?: string): string | undefined {
  const ext = getFileExtension(fileName, uri);
  if (!ext) return undefined;
  if (IMAGE_EXTS.includes(ext)) return ext === 'jpg' ? 'image/jpeg' : `image/${ext}`;
  if (VIDEO_EXTS.includes(ext)) return ext === 'mov' ? 'video/quicktime' : 'video/mp4';
  if (TEXT_EXTS.includes(ext)) {
    if (ext === 'md') return 'text/markdown';
    if (ext === 'rtf') return 'text/rtf';
    return 'text/plain';
  }
  if (ext === 'pdf') return 'application/pdf';
  if (OFFICE_EXTS.includes(ext)) {
    if (ext === 'doc') return 'application/msword';
    if (ext === 'docx') return 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
    if (ext === 'xls') return 'application/vnd.ms-excel';
    if (ext === 'xlsx') return 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
    if (ext === 'ppt') return 'application/vnd.ms-powerpoint';
    if (ext === 'pptx') return 'application/vnd.openxmlformats-officedocument.presentationml.presentation';
  }
  return undefined;
}

export function inferAttachmentPreviewKind(fileName?: string, uri?: string): AttachmentPreviewKind {
  const ext = getFileExtension(fileName, uri);
  if (IMAGE_EXTS.includes(ext)) return 'image';
  if (VIDEO_EXTS.includes(ext)) return 'video';
  if (ext === 'pdf') return 'pdf';
  if (TEXT_EXTS.includes(ext)) return 'text';
  if (OFFICE_EXTS.includes(ext)) return 'office';
  return 'file';
}

export function isVideoFileLike(fileName?: string, mimeType?: string): boolean {
  const mime = (mimeType || '').trim().toLowerCase();
  if (mime.startsWith('video/')) return true;
  return inferAttachmentPreviewKind(fileName) === 'video';
}
