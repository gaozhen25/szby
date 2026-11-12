import type { ReactNode } from 'react';
import { Image } from 'react-native';
import { Typography } from 'antd';
import { APP_NAME } from '@/lib/api-host';
import { PondRipple } from '@/ui/web/bits/PondRipple';
import { webColor } from '@/ui/web/theme';

const logoMod = require('../../../../assets/images/icon-qinghui.png');

function assetUri(mod: unknown): string {
  if (typeof mod === 'string') return mod;
  if (mod && typeof mod === 'object') {
    const rec = mod as { uri?: string; default?: unknown };
    if (typeof rec.uri === 'string' && rec.uri) return rec.uri;
    if (typeof rec.default === 'string' && rec.default) return rec.default;
  }
  try {
    return Image.resolveAssetSource(mod as number)?.uri ?? '';
  } catch {
    return '';
  }
}

export function AuthSplit({
  eyebrow,
  children,
}: {
  eyebrow: string;
  children: ReactNode;
}) {
  return (
    <div className="qh-auth-split">
      <PondRipple className="qh-auth-waves" />
      <div className="qh-auth-main">
        <div className="qh-auth-column">
          <div className="qh-auth-head">
            <div className="qh-auth-logo-frame">
              <img src={assetUri(logoMod)} alt="" className="qh-auth-logo" />
            </div>
            <Typography.Title
              level={2}
              className="qh-auth-product"
              style={{ letterSpacing: 0.4, color: webColor.nameLabel }}
            >
              {APP_NAME}
            </Typography.Title>
            <Typography.Text className="qh-auth-eyebrow">{eyebrow}</Typography.Text>
          </div>
          {children}
        </div>
      </div>
    </div>
  );
}
