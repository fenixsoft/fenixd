import { Tag } from 'antd';
import type { ReactNode } from 'react';
// v1 风格状态徽标：透明底 + 彩色文字 + 45% 透明度同色描边
// 色相取 theme.ts 宿主对齐状态色（dsh state palette；DESIGN.md「宿主对齐基线」）；
// aqua 青=出题语义 SPEC 指定色，与 progressPhase TRACK_CYAN 同 ramp，豁免对齐。
// dashboard-dark-theme 4.2：TONE_HEX 改经 useDshPalette 按档取值——浅档值与
// 改造前逐字节一致（零回退）；深档 link→#7aaaff、error→#f25a5a（design.md D2
// 映射表），success/warning/aqua 双档同值（alpha 描边 `${hex}73` 深档 hex 同构）。
import { useDshPalette, useThemeScheme } from '@/utils/themeHooks';

/** 出题语义 SPEC 指定青（豁免对齐），双档同值。 */
const TONE_AQUA = '#13c2c2';

/** muted 态描边/填充灰：浅档 #595959（现状）；深档对齐 OV_TEXT_TERTIARY_DARK
 *  可读档 #8b8f94（theme.ts 深档常量，配色单源）。 */
const MUTED_NEUTRAL = { light: '#595959', dark: '#8b8f94' } as const;

// tone→antd 预设色映射（单源：topology/index.tsx 大屏状态 Tag 消费，避免
// 内联副本取值风格漂移——code-review item 5f88cf8a2a02；原 detail.tsx 头部
// 消费方已迁移 OutlinedTag，宿主对齐改造 2026-11-03）。键覆盖
// services/dashboard STATUS_META 全部 6 种 tone，色相与 TONE_HEX / 列表页
// TONE_DOT 同语义（warning 橙、aqua 青、info 蓝；item 7d6e6be9876c）。
// 大屏域自持配色（DESIGN.md 例外域），不经此改造换轨。antd 预设名随
// darkAlgorithm 语义档自适应，双档同表。
export const TONE_TAG_COLOR: Record<string, string> = {
  muted: 'default',
  info: 'processing',
  warning: 'warning',
  critical: 'error',
  good: 'success',
  aqua: 'cyan',
};

export function OutlinedTag({
  tone,
  children,
  filled,
}: {
  tone: keyof ReturnType<typeof useToneHex>;
  children: ReactNode;
  filled?: boolean;
}) {
  const hex = useToneHex()[tone];
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
    <Tag style={{ ...shared, borderColor: MUTED_NEUTRAL[useThemeScheme()] }}>{children}</Tag>
  );
}

/** tone→色相表（渲染期按档构建；浅档值与改造前 TONE_HEX 逐字节一致）。 */
function useToneHex() {
  const pal = useDshPalette();
  return {
    muted: null,
    info: pal.link,
    warning: pal.warning,
    critical: pal.error,
    good: pal.success,
    aqua: TONE_AQUA,
  } as const;
}
