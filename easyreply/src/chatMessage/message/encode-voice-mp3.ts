/** Native：录音已是 m4a/mp4 容器，上传时改用白名单 video/mp4，无需转 mp3 */
export async function encodeVoiceBlobToMp3(input: Blob): Promise<Blob> {
  return input;
}
