// PageTitleBar.tsx — 全站统一内容标题栏控件（unified-page-title-bar 1.1）。
//
// 四类声明槽位（title / subtitle / back / filters），页面只声明数据、禁止逐页
// 自画同类型标题 div。壳位判定收敛在本组件内，页面侧零环境分支：
// - 行壳位：embed=1（dsh 面板桥 iframe，无顶栏）或视口 <768px（移动端顶栏维持
//   纯品牌）时，渲染为内容区首行标题栏，底缘 DSH_SPLIT 细线。双档形态：
//   embed 档 = 60px 半透明 soft 玻璃底（DSH_BG_SOFT_GLASS ≡ DSH_BG_SOFT 60%）+
//   backdrop blur(8px)（复刻 standalone fixedHeader 毛玻璃，2026-11-05 用户指令）
//   + sticky 钉住视口顶（滚动发生在下方内容区，标题栏不随滚；2026-11-05
//   用户定调 min-height 60）；
//   移动端档 = 1.1 原形态（48px 白底随文档流，未获指令不动）。
// - 顶栏壳位：独立访问 ≥768px 时向模块级注册表登记 meta，由 app.tsx 顶栏插槽
//   （HeaderSlot / FiltersSlot）消费渲染——标题区在 Fenix Harness 品牌之后、
//   过滤项在顶栏右上角（原全局面包屑槽位）。
//
// 壳位判定单源互斥：行壳位时不注册、顶栏壳位时不渲染行节点——同一 meta 任一
// 时刻只渲染于一处壳位；判定条件（embed / isMobile）翻转时旧壳位节点随 effect
// 清理（注销或卸载行节点），不出现双标题并存或切换残留。
//
// 形态基准（UI 真相源）：spec/changes/unified-page-title-bar/specs/
// unified-page-title-bar/prototype/（standalone.html / embed.html）——标题
// 18px/700、副标题 12px 三级灰基线随迁、计数 tabular-nums、过滤项 28px small
// 档、行壳位底缘细线；配色全部取 theme.ts 单源，零新色。落地后修订
// （2026-11-05 用户定调）：embed 档行壳位 60px/soft 底/sticky（上方注释）、
// 顶栏标题缩进 16→104。
//
// 迁移页配套约定：PageContainer 保留本体承载留白 token，但须写 `title={false}`
// 显式抑制页头——不传 title 时 PageContainer 会从路由上下文兜底取路由名渲染
// 自动页头（pro-layout renderPageHeader 的 `!title && title !== false` 分支），
// 与本控件双标题并存（3.2 实拍抓出）。PagePlaceholder 兜底占位页豁免
// （保留路由名页头形态，specs 豁免条款）。

import {
  useEffect,
  useLayoutEffect,
  useRef,
  useSyncExternalStore,
  type ReactNode,
} from 'react';
import { useIsMobile } from '@/hooks/useIsMobile';
import { isEmbedMode } from '@/utils/embedMount';
import {
  getPageTitleBarMeta,
  setPageTitleBarMeta,
  subscribePageTitleBar,
  type PageTitleBarMeta,
} from './pageTitleBarStore';
import { DSH_BG_SOFT_GLASS, DSH_SPLIT, DSH_TEXT, DSH_TEXT_SECONDARY, DSH_TEXT_TERTIARY } from '@/theme';

export type { PageTitleBarMeta } from './pageTitleBarStore';

// CSR（umi hash 路由）下用 layout effect：注册在浏览器绘制前完成，顶栏标题
// 不闪帧。node 测试环境（无 window）退回普通 effect。
const useIsomorphicLayoutEffect = typeof window !== 'undefined' ? useLayoutEffect : useEffect;

/** 顶栏壳位注册 hook：meta 挂载即登记、null 即注销（行壳位不注册）、卸载即注销
 *  （同一 effect 的 cleanup 承担清理，路由切换瞬间旧页注销与新页注册在 React
 *  同一批 passive flush 内连续执行，插槽不会渲染到空窗）。 */
function usePageTitleBarSlot(meta: PageTitleBarMeta | null) {
  // 四字段逐个进 deps（meta 对象字面量每次渲染新建，进对象 deps 即每渲染重跑；
  // 重跑本身无害——浅比较在 store 侧抑制通知——但 deps 语义须逐字段成立）
  const title = meta?.title;
  const subtitle = meta?.subtitle;
  const back = meta?.back;
  const filters = meta?.filters;
  const latest = useRef(meta);
  latest.current = meta;
  useIsomorphicLayoutEffect(() => {
    setPageTitleBarMeta(meta === null ? null : latest.current);
    return () => {
      setPageTitleBarMeta(null);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [title, subtitle, back, filters]);
}

// ── 顶栏插槽（app.tsx headerContentRender / actionsRender 消费）────────

/** 顶栏标题区插槽：品牌（Fenix Harness）之后渲染注册的 back+title+subtitle；
 *  无注册（豁免页、路由切换瞬间）渲染空——不残留上一页内容。 */
export function PageTitleBarHeaderSlot() {
  const meta = useSyncExternalStore(subscribePageTitleBar, getPageTitleBarMeta);
  if (!meta) return null;
  return (
    <div style={{ flex: 1, display: 'flex', alignItems: 'center', minWidth: 0 }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'baseline',
          flexWrap: 'wrap',
          columnGap: 10,
          rowGap: 2,
          // 2026-11-05 用户定调 16→104：顶栏标题离品牌区再深缩进一档
          paddingLeft: 104,
          minWidth: 0,
        }}
      >
        {meta.back ? <BackArrow onBack={meta.back} /> : null}
        <TitleNode title={meta.title} />
        {meta.subtitle != null ? <SubtitleNode subtitle={meta.subtitle} /> : null}
      </div>
    </div>
  );
}

/** 顶栏右上角过滤项插槽（actionsRender 槽位，原 HeaderCrumb 位置）；
 *  无注册或页面未声明 filters 渲染空。 */
export function PageTitleBarFiltersSlot() {
  const meta = useSyncExternalStore(subscribePageTitleBar, getPageTitleBarMeta);
  if (!meta?.filters) return null;
  return <FiltersNode filters={meta.filters} />;
}

// ── 行壳位（embed / 移动端：内容区首行 48px 标题栏）────────────────────

/** 统一标题栏组件：壳位判定收敛于此。页面在返回树的顶部声明
 *  `<PageTitleBar {...meta} />`（PageContainer 之前，行壳位时即内容区首行）。 */
export function PageTitleBar(props: PageTitleBarMeta) {
  const isMobile = useIsMobile();
  // 行壳位：embed（无顶栏）或移动端（顶栏维持纯品牌）。isEmbedMode() 是文档
  // 生命周期常量，判定分支只随视口阈值翻转。
  const rowSlot = isEmbedMode() || isMobile;
  // embed 档升格固定标题带（2026-11-05 用户定调）：60px + soft 底 + sticky——
  // sticky 仍在文档流占位（定高页 FRAME_OFFSET 族只吃高度不吃定位），滚动
  // 发生在下方内容区，标题栏钉住视口顶不随滚，视觉对齐 standalone fixedHeader
  // 顶栏。移动端档维持原形态。配色单源红线：玻璃底 DSH_BG_SOFT_GLASS 为
  // DSH_BG_SOFT 的 60% 透明形态（theme.ts 同源共改，守卫测试钉住）。
  // 毛玻璃（2026-11-05 用户指令「复刻 standalone 顶栏半透明模糊」）：半透明底
  // + backdrop blur(8px)（ProLayout fixedHeader 同值），内容滚过标题带时透出
  // 模糊内容；-webkit- 前缀兜底旧移动端 webview。
  const embedChrome = isEmbedMode();
  usePageTitleBarSlot(rowSlot ? null : props);
  if (!rowSlot) return null; // 顶栏壳位：本体不渲染，交顶栏插槽呈现
  return (
    <div
      data-testid="page-title-bar-row"
      style={{
        minHeight: embedChrome ? 60 : 48,
        display: 'flex',
        alignItems: 'center',
        flexWrap: 'wrap',
        background: embedChrome ? DSH_BG_SOFT_GLASS : '#ffffff',
        borderBottom: `1px solid ${DSH_SPLIT}`,
        padding: '0 15px',
        ...(embedChrome
          ? {
              position: 'sticky',
              top: 0,
              zIndex: 20,
              backdropFilter: 'blur(8px)',
              WebkitBackdropFilter: 'blur(8px)',
            }
          : {}),
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'baseline',
          flexWrap: 'wrap',
          columnGap: 10,
          rowGap: 2,
          minWidth: 0,
          // 富标题（详情页 Tag 行）在 390px 视口自然换行不溢出
          // （mobile-detail-header-density 契约，载体迁移后语义不变）
        }}
      >
        {props.back ? <BackArrow onBack={props.back} /> : null}
        <TitleNode title={props.title} />
        {props.subtitle != null ? <SubtitleNode subtitle={props.subtitle} /> : null}
      </div>
      {props.filters ? <FiltersNode filters={props.filters} wrap /> : null}
    </div>
  );
}

// ── 槽位内部件（两壳位同构排布）──────────────────────────────────────

function BackArrow({ onBack }: { onBack: () => void }) {
  return (
    <span
      data-testid="page-title-bar-back"
      onClick={onBack}
      style={{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center', marginRight: 6, color: DSH_TEXT_SECONDARY }}
    >
      {/* 返回箭头：14px 细描边（1.4）chevron，形态对齐原型 titlebar-back */}
      <svg width={14} height={14} viewBox="0 0 14 14" fill="none" aria-hidden="true">
        <path d="M9 2.5 4.5 7 9 11.5" stroke="currentColor" strokeWidth={1.4} strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </span>
  );
}

function TitleNode({ title }: { title: ReactNode }) {
  return (
    <span data-testid="page-title-bar-title" style={{ fontSize: 18, fontWeight: 700, color: DSH_TEXT, lineHeight: '24px' }}>
      {title}
    </span>
  );
}

function SubtitleNode({ subtitle }: { subtitle: ReactNode }) {
  return (
    <span data-testid="page-title-bar-subtitle" style={{ fontSize: 12, fontWeight: 400, color: DSH_TEXT_TERTIARY }}>
      {subtitle}
    </span>
  );
}

function FiltersNode({ filters, wrap }: { filters: ReactNode; wrap?: boolean }) {
  return (
    <div
      data-testid="page-title-bar-filters"
      style={{
        ...(wrap ? { marginLeft: 'auto' } : {}),
        display: 'flex',
        alignItems: 'center',
        flexWrap: wrap ? 'wrap' : undefined,
        columnGap: 8,
        rowGap: 4,
      }}
    >
      {filters}
    </div>
  );
}

/** 副标题计数的 tabular-nums 排版（spec「副标题随迁」：跨项目概览「监控 N 个
 *  项目」、项目列表「共 N 个 SPEC」等计数跨位宽稳定）。 */
export function TitleBarNum({ children }: { children: ReactNode }) {
  return <span style={{ fontVariantNumeric: 'tabular-nums' }}>{children}</span>;
}
