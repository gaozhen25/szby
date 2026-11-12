export async function saveAttachment(params: {
  url: string;
  fileName: string;
}): Promise<void> {
  const url = params.url.trim();
  if (!url) throw new Error('文件地址无效');

  try {
    const res = await fetch(url);
    const blob = await res.blob();
    const href = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = href;
    a.download = params.fileName || `attachment-${Date.now()}`;
    a.rel = 'noopener';
    a.click();
    setTimeout(() => URL.revokeObjectURL(href), 1000);
    return;
  } catch {
    const a = document.createElement('a');
    a.href = url;
    a.download = params.fileName || `attachment-${Date.now()}`;
    a.rel = 'noopener';
    a.target = '_blank';
    a.click();
  }
}
export async function saveAttachmentWeb(params: {
  url: string;
  fileName: string;
}): Promise<void> {
  const url = params.url.trim();
  if (!url) throw new Error('文件地址无效');

  try {
    const res = await fetch(url);
    const blob = await res.blob();
    const href = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = href;
    a.download = params.fileName || `attachment-${Date.now()}`;
    a.rel = 'noopener';
    a.click();
    setTimeout(() => URL.revokeObjectURL(href), 1000);
    return;
  } catch {
    const a = document.createElement('a');
    a.href = url;
    a.download = params.fileName || `attachment-${Date.now()}`;
    a.rel = 'noopener';
    a.target = '_blank';
    a.click();
  }
}
