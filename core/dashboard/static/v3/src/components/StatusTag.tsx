import { Tag } from 'antd';
import type { ReactNode } from 'react';

// v1 风格状态徽标：透明底 + 彩色文字 + 45% 透明度同色描边
const TONE_HEX: Record<string, string | null> = {
  muted: null,
  info: '#1677ff',
  warning: '#faad14',
  critical: '#ff4d4f',
  good: '#52c41a',
  aqua: '#13c2c2',
};

export function OutlinedTag({ tone, children }: { tone: string; children: ReactNode }) {
  const hex = TONE_HEX[tone];
  return hex ? (
    <Tag style={{ marginInlineEnd: 0, color: hex, borderColor: `${hex}73`, background: 'transparent', borderRadius: 10, fontSize: 12 }}>
      {children}
    </Tag>
  ) : (
    <Tag style={{ marginInlineEnd: 0 }}>{children}</Tag>
  );
}
