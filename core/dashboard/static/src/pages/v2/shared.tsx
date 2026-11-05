// v2 Bento 共享原语（redesign-dashboard-v2-ui）：六页复用的页壳 / 胶囊徽标 /
// 图标。全部色值取自 theme.tsx 单源；样式在 v2.less（.v2-page 作用域钉死，
// v2 域外零生效）。

import { Tag } from 'antd';
import type { CSSProperties, ReactNode } from 'react';
import { statusMeta } from '@/services/dashboard';
import './v2.less';
import {
  useV2IsMobile,
  V2ConfigProvider,
  V2_PILL_RADIUS,
  V2_TONE,
  V2_TEXT_SECONDARY,
  V2_WHITE,
} from './theme';

/** v2 页壳：局部 Bento 主题 + 浅灰页底 + 1400px 居中内容列（原型 main 形态）。 */
export function V2Page({ children }: { children: ReactNode }) {
  return (
    <V2ConfigProvider>
      <div className="v2-page">
        <div className="v2-inner">{children}</div>
      </div>
    </V2ConfigProvider>
  );
}

/** 语义胶囊徽标（Bento 语言：999 胶囊 + tone 软底）。filled=实底软色，outline=
 * 白底描边（原型 overview Pill 两形态）。 */
export function V2Pill({
  tone = 'muted',
  children,
  variant = 'filled',
  style,
}: {
  tone?: string;
  children: ReactNode;
  variant?: 'filled' | 'outline';
  style?: CSSProperties;
}) {
  const pair = V2_TONE[tone] || V2_TONE.muted;
  const base: CSSProperties = {
    marginInlineEnd: 0,
    borderRadius: V2_PILL_RADIUS,
    fontSize: 12,
    paddingInline: 9,
  };
  const skin: CSSProperties =
    variant === 'filled'
      ? { color: pair[0], background: pair[1], borderColor: 'transparent', fontWeight: 500 }
      : { color: pair[0], borderColor: `${pair[0]}55`, background: V2_WHITE };
  return (
    <Tag style={{ ...base, ...skin, ...style }}>{children}</Tag>
  );
}

/** SPEC 状态胶囊：label/tone 单源取 services/dashboard STATUS_META（与现产同源
 * 键域），色值经 V2_TONE 落 Bento 色板。 */
export function V2StatusPill({ status }: { status: string | null | undefined }) {
  const meta = statusMeta(status || '');
  return <V2Pill tone={meta.tone}>{meta.label}</V2Pill>;
}

/** 三点竖排操作图标（表格「操作」列 Dropdown 触发器，原型 IconDots）。 */
export function V2IconDots() {
  return (
    <svg width={14} height={14} viewBox="0 0 14 14" fill="currentColor" aria-hidden>
      <circle cx={2.6} cy={7} r={1.2} />
      <circle cx={7} cy={7} r={1.2} />
      <circle cx={11.4} cy={7} r={1.2} />
    </svg>
  );
}

/** 返回箭头（标题带左端，原型 BackArrow 形态）。title 经 aria-label 承载
 * （SVGProps 无原生 title 属性）。 */
export function V2BackArrow({ onClick, title }: { onClick: () => void; title?: string }) {
  return (
    <svg
      width={14}
      height={14}
      viewBox="0 0 14 14"
      fill="none"
      aria-hidden
      aria-label={title}
      style={{ cursor: 'pointer', flexShrink: 0 }}
      onClick={onClick}
    >
      <path
        d="M9 2.5 4.5 7 9 11.5"
        stroke={V2_TEXT_SECONDARY}
        strokeWidth={1.4}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** 页标题带（轻产品头：22px 大标题 + 副标题行；移动形态 20px 收纳，富组合
 * 允许换行防溢出）。右侧富组合由各页 children 传入（标题带形态按各页定稿
 * 原型，豁免全站统一标题栏形态基准）。 */
export function V2TitleBand({
  title,
  subtitle,
  right,
  onBack,
  backTitle,
  children,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  right?: ReactNode;
  onBack?: () => void;
  backTitle?: string;
  children?: ReactNode;
}) {
  const mobile = useV2IsMobile();
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
      {onBack ? <V2BackArrow onClick={onBack} title={backTitle} /> : null}
      <div style={{ minWidth: 0, flex: mobile ? 1 : undefined }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          {typeof title === 'string' ? (
            <span
              style={{
                fontSize: mobile ? 20 : 22,
                fontWeight: 700,
                letterSpacing: -0.3,
                lineHeight: '28px',
              }}
            >
              {title}
            </span>
          ) : (
            title
          )}
          {children}
        </div>
        {subtitle ? (
          <div className="v2-num" style={{ fontSize: 13, color: V2_TONE.muted[0], marginTop: 2 }}>
            {subtitle}
          </div>
        ) : null}
      </div>
      <span style={{ flex: 1 }} />
      {right}
    </div>
  );
}
