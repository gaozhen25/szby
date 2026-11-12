import { Image, type ImageProps } from 'expo-image';

type CachedImageProps = ImageProps;

function resolveContentFit(
  contentFit: ImageProps['contentFit'],
  resizeMode: ImageProps['resizeMode'],
): ImageProps['contentFit'] {
  if (contentFit) return contentFit;
  switch (resizeMode) {
    case 'contain':
      return 'contain';
    case 'stretch':
      return 'fill';
    case 'center':
      return 'none';
    case 'cover':
    default:
      return 'cover';
  }
}

/** 聊天相关远程图片：默认 memory-disk 缓存（iOS SDWebImage / Android Glide） */
export function CachedImage({
  cachePolicy = 'memory-disk',
  contentFit,
  resizeMode,
  ...props
}: CachedImageProps) {
  return (
    <Image
      {...props}
      cachePolicy={cachePolicy}
      contentFit={resolveContentFit(contentFit, resizeMode)}
    />
  );
}
