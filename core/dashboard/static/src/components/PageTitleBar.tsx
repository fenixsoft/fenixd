// PageTitleBar.tsx — 全站统一内容标题栏控件（unified-page-title-bar 1.1）。
//
// 四类声明槽位（title / subtitle / back / filters），页面只声明数据、禁止逐页
// 自画同类型标题 div。壳位判定收敛在本组件内，页面侧零环境分支：
// - 顶栏壳位：standalone 访问（桌面与移动端，2026-11-06 用户指令「移动端标题
//   并入最顶那条带 logo/汉堡的顶栏」——原移动端独立行壳位 48px 档退役；副标题
//   移动端不显示）向模块级注册表登记 meta，由 app.tsx 顶栏插槽（HeaderSlot /
//   FiltersSlot）消费渲染——标题区在 Fenix Harness 品牌之后、过滤项在顶栏右上
//   角（原全局面包屑槽位）。
// - 行壳位：仅 embed=1（dsh 面板桥 iframe，无顶栏），渲染为内容区首行标题栏，
//   底缘 DSH_SPLIT 细线。形态 = 60px 半透明 soft 玻璃底（DSH_BG_SOFT_GLASS ≡
//   DSH_BG_SOFT 60%）+ backdrop blur(8px) + sticky 钉住视口顶（滚动发生在下方
//   内容区，标题栏不随滚；2026-11-05 用户定调 min-height 60；2026-11-06 用户
//   指令「标题栏只换染色 rgb(249,250,251) 保留毛玻璃」——玻璃染色随 soft 单源，
//   形态不变）。
//
// 壳位判定单源互斥：行壳位时不注册、顶栏壳位时不渲染行节点——同一 meta 任一
// 时刻只渲染于一处壳位；判定条件（embed）翻转时旧壳位节点随 effect 清理
// （注销或卸载行节点），不出现双标题并存或切换残留。
//
// 形态基准（UI 真相源）：spec/changes/unified-page-title-bar/specs/
// unified-page-title-bar/prototype/（standalone.html / embed.html）——标题
// 18px/700、副标题 12px 三级灰基线随迁、计数 tabular-nums、过滤项 28px small
// 档、行壳位底缘细线；配色全部取 theme.ts 单源，零新色。落地后修订
// （2026-11-05 用户定调）：embed 档行壳位 60px/soft 底/sticky（上方注释）、
// 顶栏标题缩进 16→104；（2026-11-06 用户指令）：标题栏只换 soft 染色保留
// 毛玻璃（上方注释）、菜单侧栏底色 soft 实底（theme.ts dshLayoutToken）、
// 移动端标题并入顶栏+副标题移动端隐藏（顶栏缩进移动档 104→8）。
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
import { DSH_BG_SOFT, DSH_BG_SOFT_GLASS, DSH_SPLIT, DSH_TEXT, DSH_TEXT_SECONDARY, DSH_TEXT_TERTIARY } from '@/theme';

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
 *  无注册（豁免页、路由切换瞬间）渲染空——不残留上一页内容。standalone 桌面
 *  与移动端共用本插槽（2026-11-06 用户指令：移动端标题并入最顶顶栏）：移动档
 *  缩进 104→8（品牌区窄，深缩进会把标题顶出视口），副标题移动端不显示。 */
export function PageTitleBarHeaderSlot() {
  const meta = useSyncExternalStore(subscribePageTitleBar, getPageTitleBarMeta);
  const isMobile = useIsMobile();
  if (!meta) return null;
  return (
    <div style={{ flex: 1, display: 'flex', alignItems: 'center', minWidth: 0 }}>
      <div
        style={{
          display: 'flex',
          // center（2026-11-06 用户指令「标题左边的箭头在标题栏中垂直居中」）：
          // 详情页富标题内含中文标题下方行后整体变高，baseline 会让箭头钉在
          // 首行基线显得偏高——改居中随标题块（含多行）整体取中
          alignItems: 'center',
          flexWrap: 'wrap',
          columnGap: 10,
          rowGap: 2,
          // 2026-11-05 用户定调桌面 16→104：顶栏标题离品牌区再深缩进一档；
          // 移动档 8（2026-11-06，汉堡+logo 后贴排）
          paddingLeft: isMobile ? 8 : 104,
          minWidth: 0,
        }}
      >
        {/* 返回箭头移动端不渲染（2026-11-06 用户指令「标题的左边箭头在移动
            设备中也不用显示」）：移动端导航走系统返回/菜单，桌面保持 */}
        {meta.back && !isMobile ? <BackArrow onBack={meta.back} /> : null}
        <TitleNode title={meta.title} />
        {meta.subtitle != null && !isMobile ? <SubtitleNode subtitle={meta.subtitle} /> : null}
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

// ── 行壳位（仅 embed=1，60px sticky 玻璃带）；移动端并入顶栏──────────────

/** 统一标题栏组件：壳位判定收敛于此。页面在返回树的顶部声明
 *  `<PageTitleBar {...meta} />`（PageContainer 之前，行壳位时即内容区首行）。 */
export function PageTitleBar(props: PageTitleBarMeta) {
  const isMobile = useIsMobile();
  // 行壳位（2026-11-06 用户指令改版）：仅 embed=1（dsh 面板桥 iframe，无顶栏）。
  // 移动端不再落行壳位——页面标题并入最顶层顶栏（logo/汉堡那条，同 standalone
  // 桌面注册-插槽路径），内容区不再独立铺标题带；副标题移动端不显示（同指令，
  // 见 HeaderSlot 与行壳位两处 !isMobile 条件）。isEmbedMode() 是文档生命周期
  // 常量，判定分支不随视口翻转（移动端注册进顶栏后，跨 768 阈值 resize 无壳位
  // 迁移，仅缩进/副标题档位随 isMobile 变化）。
  const rowSlot = isEmbedMode();
  // embed 档固定标题带：60px + sticky——sticky 仍在文档流占位（定高页
  // FRAME_OFFSET 族只吃高度不吃定位），滚动发生在下方内容区，标题栏钉住视口顶
  // 不随滚。配色（2026-11-06 用户指令「标题栏只是改变颜色，保留毛玻璃」）：
  // 玻璃底 DSH_BG_SOFT_GLASS（DSH_BG_SOFT 60% 透明形态，theme.ts 同源共改，
  // 守卫测试钉住）+ backdrop blur(8px)（半透明底是毛玻璃生效前提，回实底即
  // 静默失效）。底缘细线 DSH_SPLIT 与 standalone 顶栏下边框、侧栏右边框同值
  // （用户指令三者一致）。
  usePageTitleBarSlot(rowSlot ? null : props);
  if (!rowSlot) return null; // 顶栏壳位：本体不渲染，交顶栏插槽呈现
  return (
    <div
      data-testid="page-title-bar-row"
      style={{
        minHeight: 60,
        display: 'flex',
        alignItems: 'center',
        flexWrap: 'wrap',
        background: DSH_BG_SOFT_GLASS,
        borderBottom: `1px solid ${DSH_SPLIT}`,
        padding: '0 15px',
        position: 'sticky',
        top: 0,
        zIndex: 20,
        backdropFilter: 'blur(8px)',
        WebkitBackdropFilter: 'blur(8px)',
      }}
    >
      <div
        style={{
          display: 'flex',
          // center（2026-11-06 用户指令「标题左边的箭头在标题栏中垂直居中」，
          // 顶栏插槽同款）：箭头随标题块（含详情页中文标题下方行）整体取中
          alignItems: 'center',
          flexWrap: 'wrap',
          columnGap: 10,
          rowGap: 2,
          minWidth: 0,
          // 富标题（详情页 Tag 行）在 390px 视口自然换行不溢出
          // （mobile-detail-header-density 契约，载体迁移后语义不变）
        }}
      >
        {/* 返回箭头移动端不渲染（同顶栏插槽指令，embed iframe 移动设备同款） */}
        {props.back && !isMobile ? <BackArrow onBack={props.back} /> : null}
        <TitleNode title={props.title} />
        {/* 副标题只在非移动壳位渲染（2026-11-06 用户指令「副标题在移动设备
            模式中不显示」）：移动档 48px 窄幅密度考虑，桌面顶栏与 embed 档
            （60px，桌面 iframe 语境）不受影响 */}
        {props.subtitle != null && !isMobile ? <SubtitleNode subtitle={props.subtitle} /> : null}
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
    // minWidth 0（flex 项默认 min-width:auto 会撑住富节点内部第二行的
    // min-content）——详情页富标题内含「中文标题下方行」单行省略，须允许
    // 本项收缩到可用宽，省略号才能生效（spec-detail-page-scope 约定）
    <span data-testid="page-title-bar-title" style={{ fontSize: 18, fontWeight: 700, color: DSH_TEXT, lineHeight: '24px', minWidth: 0 }}>
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
