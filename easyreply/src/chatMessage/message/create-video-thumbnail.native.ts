import * as VideoThumbnails from 'expo-video-thumbnails';

export type VideoThumbnailResult = {
  uri: string;
  width: number;
  height: number;
  blob?: Blob;
};

/** Native：用 expo-video-thumbnails 截取封面帧 */
export async function createVideoThumbnail(uri: string): Promise<VideoThumbnailResult> {
  const result = await VideoThumbnails.getThumbnailAsync(uri, { time: 0, quality: 0.7 });
  return {
    uri: result.uri,
    width: result.width || 398,
    height: result.height || 224,
  };
}
