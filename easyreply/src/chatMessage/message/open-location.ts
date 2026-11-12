import { Linking, Platform } from 'react-native';

async function tryOpenUrl(url: string): Promise<boolean> {
  try {
    await Linking.openURL(url);
    return true;
  } catch {
    return false;
  }
}

/**
 * 打开聊天位置消息（contentType=109）
 * Web：高德 H5；Android：优先原生高德 scheme；iOS：Apple Maps
 *
 * 注意：Android 不要把 encodeURIComponent 后的中文塞进 geo: 标题或高德 poiname，
 * 否则高德会把 %E5%A4%A9… 原样显示。
 */
export async function openChatLocation(params: {
  latitude: number;
  longitude: number;
  description?: string;
}): Promise<void> {
  const { latitude, longitude } = params;
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) {
    throw new Error('位置坐标无效');
  }
  const name = (params.description || '').trim() || '位置';
  // HTTP(S) 查询串用编码；原生高德 scheme 的 poiname 用明文（避开 &?#）
  const encodedName = encodeURIComponent(name);
  const amapPoiName = name.replace(/[&?#]/g, ' ').trim() || '位置';

  if (Platform.OS === 'web') {
    const url = `https://uri.amap.com/marker?position=${longitude},${latitude}&name=${encodedName}`;
    if (typeof window === 'undefined') throw new Error('当前环境无法打开地图');
    window.open(url, '_blank', 'noopener,noreferrer');
    return;
  }

  if (Platform.OS === 'ios') {
    await Linking.openURL(`http://maps.apple.com/?ll=${latitude},${longitude}&q=${encodedName}`);
    return;
  }

  const candidates = [
    `androidamap://viewMap?sourceApplication=QingHui&poiname=${amapPoiName}&lat=${latitude}&lon=${longitude}&dev=0`,
    `amapuri://viewMap?sourceApplication=QingHui&poiname=${amapPoiName}&lat=${latitude}&lon=${longitude}&dev=0`,
    // 仅坐标，避免 geo 括号标题乱码
    `geo:${latitude},${longitude}?q=${latitude},${longitude}`,
    `https://uri.amap.com/marker?position=${longitude},${latitude}&name=${encodedName}`,
  ];

  for (const url of candidates) {
    if (await tryOpenUrl(url)) return;
  }
  throw new Error('无法打开地图');
}
