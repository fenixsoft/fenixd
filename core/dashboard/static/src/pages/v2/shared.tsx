// v2 Bento 共享原语（redesign-dashboard-v2-ui）：六页复用的页壳 / 胶囊徽标 /
// 图标。全部色值取自 theme.tsx 单源；样式在 v2.less（.v2-page 作用域钉死，
// v2 域外零生效）。

import { Tag } from 'antd';
import type { CSSProperties, ReactNode } from 'react';
import { statusMeta } from '@/services/dashboard';
import './v2.less';
import { V2ConfigProvider, V2_PILL_RADIUS, V2_TONE, V2_WHITE } from './theme';

/** v2 页壳：局部 Bento 主题 + 浅灰页底 + 1400px 居中内容列（原型 main 形态）。
 * variant="overview"：概览页变体（白底 + 内容列随外部容器满宽、左右固定 30px，
 * 样式镜像 v2.less `.v2-page.v2-overview`）；variant="projects"：项目详情页变体
 * （同 overview 白底满宽 30px 形态，2026-11-06 用户指令「v2 项目页背景改纯白 +
 * 表格撑满容器」，镜像 `.v2-page.v2-projects`）；variant="white"：仅页底改白、
 * 居中列不变（2026-11-06 用户指令「v2 帮助中心背景改白」，镜像
 * `.v2-page.v2-white`），缺省形态不变。
 * titleBar：统一标题栏声明（2026-11-06 用户指令「v2 页标题收编全站统一标题栏
 * 控件」——六页自画 V2TitleBand 标题带整体退役）。渲染在 `.v2-page` 直下、
 * `.v2-inner` 之前：行壳位（embed 档 60px sticky；2026-11-06 二次指令后移动端
 * 行壳位退役、标题随顶栏 HeaderSlot，本槽位结构对移动端同样无害）满宽贴顶
 * （sticky 钉视口顶依赖此结构，进 .v2-inner 会被 1400px 收窄 + 页顶内边距架空）；
 * standalone 桌面控件本体渲染 null，标题经注册表落 ProLayout 顶栏插槽。 */
export function V2Page({
  children,
  variant,
  titleBar,
}: {
  children: ReactNode;
  variant?: 'overview' | 'white' | 'projects';
  titleBar?: ReactNode;
}) {
  const cls =
    variant === 'overview'
      ? 'v2-page v2-overview'
      : variant === 'white'
        ? 'v2-page v2-white'
        : variant === 'projects'
          ? 'v2-page v2-projects'
          : 'v2-page';
  return (
    <V2ConfigProvider>
      <div className={cls}>
        {titleBar}
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

/** 页标题带已退役（2026-11-06 用户指令「v2 页标题收编全站统一标题栏控件」）：
 * 六页（overview / projectDetail / specDetail / settings / help / ops）全部改经
 * `<V2Page titleBar={<PageTitleBar … />}>` 声明标题元数据（title/subtitle/back/
 * filters 四槽位，壳位判定收敛在控件内），本组件与配套 V2BackArrow 已删除，
 * 守卫 tests/v2TitleBarGuard.test.mjs 钉死勿回填。 */
