import { Tag } from 'antd';

/**
 * 「快速/完整模式」标记单源（code-review item 504cf2d4b647）：列表桌面「模式」
 * 列、移动卡片与详情页（标题旁标记、SPEC 切换列表执行模式列）共用同一判据/
 * 文案/配色——fast-track → cyan「快速模式」，其余（含存量无 mode 字段的 spec）
 * 按缺省 full 展示「完整模式」。调整模式语义只改此处。
 *
 * compact：详情页 SPEC 切换列表行内的小号形态（12px/紧凑 padding）。
 */
export function ModeTag({ mode, compact = false }: { mode?: string | null; compact?: boolean }) {
  const isFast = mode === 'fast-track';
  return (
    <Tag
      color={isFast ? 'cyan' : 'default'}
      style={
        compact
          ? { marginInlineEnd: 0, fontSize: 12, lineHeight: '18px', paddingInline: 5, paddingBlock: 0 }
          : { marginInlineEnd: 0 }
      }
    >
      {isFast ? '快速模式' : '完整模式'}
    </Tag>
  );
}
