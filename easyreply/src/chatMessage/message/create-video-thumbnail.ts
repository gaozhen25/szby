export type VideoThumbnailResult = {
  uri: string;
  width: number;
  height: number;
  blob?: Blob;
};

/** Metro 默认入口；实际由 .native / .web 解析 */
export async function createVideoThumbnail(_uri: string): Promise<VideoThumbnailResult> {
  throw new Error('createVideoThumbnail: unsupported platform');
}
