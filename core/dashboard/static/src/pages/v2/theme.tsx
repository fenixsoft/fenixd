// theme.tsx — v2 商业化界面域主题单源（redesign-dashboard-v2-ui 1.1）。
//
// Bento 磁贴设计语言（定稿原型 spec/changes/redesign-dashboard-v2-ui/prototype/
// 提取，UI 真相源）：浅灰页底白磁贴大圆角软阴影、黑主色按钮 + 蓝链接、语义胶囊
// 徽标、tabular-nums 数字排版。全部页面色值只准取自本文件常量（DESIGN.md
// 「例外域：v2 商业化界面域」配色单源条款），MUST NOT import 现产 theme.ts
// 色值——宪法配色单源在 v2 域经修正案后由本文件承载，两域各自单源互不引用。
// v2 域外任何页面 MUST NOT import 本文件（例外域约束）。

import { ConfigProvider } from 'antd';
import type { ReactNode } from 'react';
import { useIsMobile } from '@/hooks/useIsMobile';

// ── 页面底色与磁贴 ──

/** 页底浅灰（磁贴层次底；一般域为白底，v2 域偏离已登记）。 */
export const V2_BG = '#f8fafc';
/** 白磁贴：圆角 16 + 细边框 + 软阴影（.v2-bento 类，样式镜像见 v2.less）。 */
export const V2_TILE_RADIUS = 16;
export const V2_TILE_BORDER = '#eef2f7';
export const V2_TILE_SHADOW =
  '0 1px 3px rgba(15, 23, 42, 0.05), 0 1px 2px rgba(15, 23, 42, 0.03)';
/** 胶囊徽标圆角（语义胶囊 999）。 */
export const V2_PILL_RADIUS = 999;

// ── 文字四阶（定稿原型 slate 阶） ──

export const V2_TEXT = '#1e293b';
export const V2_TEXT_SECONDARY = '#475569';
export const V2_TEXT_TERTIARY = '#64748b';
export const V2_TEXT_QUATERNARY = '#94a3b8';

// ── 主色黑系（主按钮 / ACTIVE 分段按钮） ──

export const V2_PRIMARY = '#0f1115';
export const V2_PRIMARY_HOVER = '#43454a';
export const V2_PRIMARY_ACTIVE = '#2c2c2e';

// ── 链接与输入焦点蓝 ──

export const V2_LINK = '#4176e6';
export const V2_LINK_FOCUS_SHADOW = '0 0 0 2px rgba(65, 118, 230, 0.12)';

// ── 语义色（候选方案 B 定稿色板；v2 域 error/warning 与一般域 dsh 值不同） ──

export const V2_SUCCESS = '#22c55e';
export const V2_ERROR = '#dc2626';
export const V2_WARNING = '#d97706';

// ── 阶段进度 ramp（出题青 / 实现蓝 / 门禁橙 / 验证绿，与任务进度列同构） ──

export const V2_RAMP_PLANNING = '#0891b2';
export const V2_RAMP_IMPLEMENTING = '#2563eb';
export const V2_RAMP_GATES = '#ea580c';
export const V2_RAMP_VERIFYING = '#16a34a';

// ── 线与分隔 ──

export const V2_BORDER = '#e2e8f0';
export const V2_HAIRLINE = '#eef2f7';
export const V2_SPLIT = '#f1f5f9';

// ── tone 软底色（胶囊徽标 filled 形态的背景档） ──

export const V2_BLUE_SOFT = '#eff6ff';
export const V2_GREEN_SOFT = '#f0fdf4';
export const V2_AMBER_SOFT = '#fffbeb';
export const V2_RED_SOFT = '#fef2f2';
export const V2_CYAN_SOFT = '#ecfeff';
export const V2_ORANGE_SOFT = '#ffedd5';
export const V2_SLATE_SOFT = '#f1f5f9';

/** 胶囊徽标 tone 键 → [前景色, 软底色]。键域与 services/dashboard.ts 的
 * StatusTone 对齐（状态 pill 由 statusMeta 的 tone 驱动取色），info/warning/
 * critical/good/aqua 五枚 + muted 兜底。 */
export const V2_TONE: Record<string, [string, string]> = {
  info: [V2_RAMP_IMPLEMENTING, V2_BLUE_SOFT],
  warning: [V2_WARNING, V2_AMBER_SOFT],
  critical: [V2_ERROR, V2_RED_SOFT],
  good: [V2_RAMP_VERIFYING, V2_GREEN_SOFT],
  aqua: [V2_RAMP_PLANNING, V2_CYAN_SOFT],
  muted: [V2_TEXT_TERTIARY, V2_SLATE_SOFT],
};

/** 活跃 Agent 堆叠条分类色板（数据编码色，图表可辨色相；键序即图例序）。 */
export const V2_LANE_COLORS = [
  '#2563eb',
  '#f59e0b',
  '#0891b2',
  '#db2777',
  '#92710c',
  '#16a34a',
  '#dc2626',
  '#7c3aed',
];

/** 字体栈（与全站 global.less / theme.ts 同栈，v2 域独立声明不引用对方常量）。 */
export const V2_FONT_FAMILY =
  "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Helvetica Neue', Helvetica, Arial, sans-serif";

/** v2 域 antd 主题表：局部 ConfigProvider 消费，只作用于 v2 六页子树。 */
export const v2Theme = {
  token: {
    colorPrimary: V2_PRIMARY,
    colorPrimaryHover: V2_PRIMARY_HOVER,
    colorPrimaryActive: V2_PRIMARY_ACTIVE,
    colorLink: V2_LINK,
    colorInfo: V2_LINK,
    colorSuccess: V2_SUCCESS,
    colorError: V2_ERROR,
    colorWarning: V2_WARNING,
    colorText: V2_TEXT,
    colorTextSecondary: V2_TEXT_SECONDARY,
    colorTextTertiary: V2_TEXT_TERTIARY,
    colorTextQuaternary: V2_TEXT_QUATERNARY,
    colorBgLayout: V2_BG,
    colorBorder: V2_BORDER,
    colorBorderSecondary: V2_HAIRLINE,
    colorSplit: V2_SPLIT,
    borderRadius: 12,
    borderRadiusSM: 8,
    borderRadiusLG: V2_TILE_RADIUS,
    controlHeight: 32,
    controlHeightSM: 28,
    fontFamily: V2_FONT_FAMILY,
  },
  components: {
    Input: {
      activeBorderColor: V2_LINK,
      activeShadow: V2_LINK_FOCUS_SHADOW,
      hoverBorderColor: V2_TEXT_QUATERNARY,
    },
    Button: { primaryShadow: 'none', defaultShadow: 'none' },
    Table: {
      headerBg: 'transparent',
      headerColor: V2_TEXT_TERTIARY,
      headerSplitColor: 'transparent',
      rowHoverBg: V2_BG,
    },
  },
};

/** v2 局部主题包裹器：页面根节点使用，磁贴/控件在子树内取 Bento token。
 * locale 由 app.tsx 根 ConfigProvider 下传（嵌套 Provider 继承），此处只覆盖
 * 主题，不截断 AntdApp 消息上下文。 */
export function V2ConfigProvider({ children }: { children: ReactNode }) {
  return <ConfigProvider theme={v2Theme}>{children}</ConfigProvider>;
}

// ── 移动端断点单源（redesign-dashboard-v2-ui-mobile D1）──────────────────

/** 移动断点上界（不含）：视口 ≥768px 呈桌面形态，<768px 呈移动形态。与现产
 * hooks/useIsMobile.ts 的 matchMedia '(max-width: 767.98px)' 两轨同界（CSS
 * 媒体查询与 JS 判定对齐，见知识 mobile-breakpoint-unification）；v2.less 的
 * @media 镜像同值（CSS 无法 import TS 常量，两处同改）。v2 域内禁止散落
 * 断点魔法数，一律消费本 token 或 useV2IsMobile。 */
export const V2_MOBILE_MAX_WIDTH = 767.98;
export const V2_MOBILE_QUERY = `(max-width: ${V2_MOBILE_MAX_WIDTH}px)`;

/** v2 形态判定 hook（D2 形态切换单源）：六页统一消费入口，复用现产
 * useIsMobile（767.98 同界、matchMedia 同步首帧），v2 页不散落 matchMedia
 * 调用；桌面/移动两形态在页组件内按本判定分支渲染（布局容器级分支，数据层
 * 共享），MUST NOT 拆成两套路由。 */
export function useV2IsMobile(): boolean {
  return useIsMobile();
}
