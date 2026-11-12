export type VideoThumbnailResult = {
  uri: string;
  width: number;
  height: number;
  blob?: Blob;
};

/** Web：用 video + canvas 截取封面帧 */
export async function createVideoThumbnail(uri: string): Promise<VideoThumbnailResult> {
  const video = document.createElement('video');
  video.crossOrigin = 'anonymous';
  video.muted = true;
  video.playsInline = true;
  video.preload = 'auto';
  video.src = uri;

  await new Promise<void>((resolve, reject) => {
    const onError = () => reject(new Error('视频封面加载失败'));
    video.addEventListener('loadeddata', () => resolve(), { once: true });
    video.addEventListener('error', onError, { once: true });
  });

  // seek 到接近开头的一帧
  try {
    video.currentTime = Math.min(0.1, Math.max(0, (video.duration || 1) * 0.01));
    await new Promise<void>((resolve) => {
      video.addEventListener('seeked', () => resolve(), { once: true });
    });
  } catch {
    // ignore seek failures
  }

  const width = Math.max(1, video.videoWidth || 398);
  const height = Math.max(1, video.videoHeight || 224);
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('无法生成视频封面');
  ctx.drawImage(video, 0, 0, width, height);

  const blob = await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob(
      (b) => (b ? resolve(b) : reject(new Error('封面导出失败'))),
      'image/jpeg',
      0.8,
    );
  });

  return {
    uri: URL.createObjectURL(blob),
    width,
    height,
    blob,
  };
}
