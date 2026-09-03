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

export function OutlinedTag({
  tone,
  children,
  filled,
}: {
  tone: string;
  children: ReactNode;
  filled?: boolean;
}) {
  const hex = TONE_HEX[tone];
  const shared = {
    marginInlineEnd: 0,
    borderRadius: 10,
    fontSize: 12,
  } as const;
  if (filled) {
    // ant-tag-filled：浅色同色系填充底 + 原色文字（antd useColor 对自定义 hex 计算 l=0.95 背景）
    const filledStyle = { ...shared, fontWeight: 'normal' } as const;
    return hex ? (
      <Tag variant="filled" color={hex} style={filledStyle}>
        {children}
      </Tag>
    ) : (
      <Tag variant="filled" color="#595959" style={filledStyle}>
        {children}
      </Tag>
    );
  }
  return hex ? (
    <Tag style={{ ...shared, color: hex, borderColor: `${hex}73`, background: 'transparent' }}>
      {children}
    </Tag>
  ) : (
    // muted 态灰底 tag 在灰色背景（#fafafa 卡片等）中会隐形，补深灰描边
    <Tag style={{ ...shared, borderColor: '#595959' }}>{children}</Tag>
  );
}
