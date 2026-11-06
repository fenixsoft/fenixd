// 统一标题栏控件守卫（unified-page-title-bar 1.3）。
//
// 两层覆盖：
// - 行为层：注册单源（pageTitleBarStore.ts，纯 TS 零 JSX）node type-stripping
//   直载（embedMount.test.mjs 先例），覆盖注册/注销、浅比较抑制通知、订阅。
// - 接线层：PageTitleBar.tsx / app.tsx 源码扫描（pageChrome.test.mjs 习语），
//   锁定壳位判定收敛、effect 清理、插槽空渲染与互斥结构；视觉行为由
//   `npm run build` 与 playwright 实拍覆盖（任务 3.2）。
// 运行：cd core/dashboard/static && node --test tests/pageTitleBar.test.mjs
import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import {
  getPageTitleBarMeta,
  setPageTitleBarMeta,
  subscribePageTitleBar,
} from '../src/components/pageTitleBarStore.ts';

const STATIC_ROOT = join(import.meta.dirname, '..');
const readComponent = () =>
  readFileSync(join(STATIC_ROOT, 'src', 'components', 'PageTitleBar.tsx'), 'utf8');
const readApp = () => readFileSync(join(STATIC_ROOT, 'src', 'app.tsx'), 'utf8');

beforeEach(() => {
  // 每例前置注销，测试互不串态（store 是模块级单例）
  setPageTitleBarMeta(null);
});

// ════ 行为层：注册单源（注册/卸载清理、无注册渲染空、通知抑制） ════

test('注册/注销：登记后快照可见，null 注销即清空（卸载清理语义）', () => {
  const metaA = { title: '跨项目概览', subtitle: '监控 4 个项目' };
  setPageTitleBarMeta(metaA);
  assert.equal(getPageTitleBarMeta(), metaA);
  // cleanup 注销（路由切换 / 卸载）
  setPageTitleBarMeta(null);
  assert.equal(getPageTitleBarMeta(), null);
});

test('无注册渲染空：初始与注销后快照恒 null（插槽据此渲染空、不残留上一页）', () => {
  assert.equal(getPageTitleBarMeta(), null);
  setPageTitleBarMeta({ title: '设置' });
  setPageTitleBarMeta(null);
  assert.equal(getPageTitleBarMeta(), null);
});

test('路由切换换页：新页注册整体覆盖旧页 meta，四槽位逐字段替换无残留', () => {
  const metaPrev = { title: '跨项目概览', subtitle: '监控 4 个项目', filters: Symbol('f') };
  const metaNext = { title: '设置', back: () => {} };
  setPageTitleBarMeta(metaPrev);
  setPageTitleBarMeta(metaNext);
  assert.equal(getPageTitleBarMeta(), metaNext);
  assert.equal(getPageTitleBarMeta().subtitle, undefined);
  assert.equal(getPageTitleBarMeta().filters, undefined);
});

test('浅比较抑制：内容同构的新引用静默换引用不通知（页面每渲染新建 JSX 不成渲染环）', () => {
  let notified = 0;
  const unsubscribe = subscribePageTitleBar(() => {
    notified += 1;
  });
  const back = () => {};
  setPageTitleBarMeta({ title: '设置', back });
  assert.equal(notified, 1); // 首次登记通知
  // 同构新引用（模拟一次渲染新建的 JSX/箭头函数）：换引用、不通知
  setPageTitleBarMeta({ title: '设置', back });
  assert.equal(notified, 1);
  assert.notEqual(getPageTitleBarMeta(), undefined);
  // 内容实变（副标题计数刷新）才通知
  setPageTitleBarMeta({ title: '设置', subtitle: '监控 5 个项目', back });
  assert.equal(notified, 2);
  unsubscribe();
});

test('订阅退订：退订后不再收到通知', () => {
  let notified = 0;
  const unsubscribe = subscribePageTitleBar(() => {
    notified += 1;
  });
  setPageTitleBarMeta({ title: '帮助' });
  unsubscribe();
  setPageTitleBarMeta(null);
  assert.equal(notified, 1);
});

// ════ 接线层：壳位判定收敛 + 互斥结构（源码扫描） ════

test('壳位判定收敛在组件内：embed 行壳位（移动端并入顶栏），页面侧零环境分支', () => {
  const tsx = readComponent();
  // 判定单源：isEmbedMode() 收敛在 PageTitleBar 内部（2026-11-06 用户指令：
  // 移动端标题并入最顶顶栏，行壳位不再含 isMobile 档）
  assert.match(tsx, /const rowSlot = isEmbedMode\(\);/);
  // 行壳位节点与顶栏注册互斥：行壳位时不注册（null），顶栏壳位本体不渲染
  assert.match(tsx, /usePageTitleBarSlot\(rowSlot \? null : props\)/);
  assert.match(tsx, /if \(!rowSlot\) return null;/);
  // 判定输入单源：useIsMobile（matchMedia 768 断点）+ isEmbedMode（embedMount 单点）
  assert.match(tsx, /import \{ useIsMobile \} from '@\/hooks\/useIsMobile';/);
  assert.match(tsx, /import \{ isEmbedMode \} from '@\/utils\/embedMount';/);
});

test('app.tsx 顶栏插槽接线：headerContentRender 标题区 + actionsRender 过滤项（面包屑退役）', () => {
  const app = readApp();
  assert.match(app, /headerContentRender: \(\) => <PageTitleBarHeaderSlot \/>/);
  assert.match(app, /actionsRender: \(\) => \[<PageTitleBarFiltersSlot key="filters" \/>\]/);
  // 面包屑退役：HeaderCrumb 组件、crumbItems 映射、样式锚点零残留
  // （说明性注释的旧名提法豁免——剥掉块注释与行注释后只拦代码回潮）
  const codeOnly = app.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
  assert.doesNotMatch(codeOnly, /HeaderCrumb|crumbItems|safeDecode|global-header-crumb|Breadcrumb/);
  // 槽位组件消费注册单源（useSyncExternalStore），无注册渲染空
  const tsx = readComponent();
  assert.match(tsx, /useSyncExternalStore\(subscribePageTitleBar, getPageTitleBarMeta\)/);
  assert.match(tsx, /if \(!meta\) return null;/);
  // 顶栏标题缩进（2026-11-05 用户定调 16→104：标题离品牌区再深缩进一档；
  // 2026-11-06 用户指令移动档并入顶栏后收窄 8 贴排汉堡+logo）
  assert.match(tsx, /paddingLeft: isMobile \? 8 : 104,/);
  // 副标题移动端不显示（2026-11-06 用户指令）：顶栏插槽与行壳位两处 !isMobile
  assert.match(tsx, /meta\.subtitle != null && !isMobile \? <SubtitleNode subtitle=\{meta\.subtitle\} \/>/);
  assert.match(tsx, /props\.subtitle != null && !isMobile \? <SubtitleNode subtitle=\{props\.subtitle\} \/>/);
});

test('注册随卸载清理：同一 effect cleanup 注销（路由切换瞬间旧注销+新注册同批 flush）', () => {
  const tsx = readComponent();
  // layout effect（绘制前注册，顶栏不闪帧）+ cleanup 注销在同一 effect 内
  assert.match(tsx, /useIsomorphicLayoutEffect\(/);
  assert.match(
    tsx,
    /setPageTitleBarMeta\(meta === null \? null : latest\.current\);\s*return \(\) => \{\s*setPageTitleBarMeta\(null\);\s*\};/,
  );
});

test('壳位互斥：跨阈值 resize 时旧壳位随 deps 翻转清理（四字段 deps + 行壳位 null 注册）', () => {
  const tsx = readComponent();
  // deps 逐字段（含 rowSlot 翻转传导：null 档四字段全 undefined → 翻转必变 deps）
  assert.match(tsx, /\}, \[title, subtitle, back, filters\]\);/);
  // 行壳位渲染前先清理顶栏注册语义由 hook 参数 null 承担（见上例），此处锁定
  // 行壳位节点只渲染一份（无第二处标题渲染路径）
  const rowRendering = tsx.match(/if \(!rowSlot\) return null;[^\n]*\n\s*return \(/g);
  assert.equal(rowRendering?.length, 1);
});

test('行壳位形态锚点：embed 档 60px soft 染色玻璃底 sticky 毛玻璃 + DSH_SPLIT 底缘细线 + 同构槽位件（theme.ts 单源配色；移动端档随标题并入顶栏退役）', () => {
  const tsx = readComponent();
  // 2026-11-05 用户定调 embed 固定标题带（60 / sticky 钉视口顶）；2026-11-06
  // 用户指令「标题栏只是改变颜色，保留毛玻璃」：玻璃底 soft 染色（形态不变）；
  // 同日「移动端标题并入顶栏」：行壳位收敛为 embed 单档，48px 移动档退役
  assert.match(tsx, /minHeight: 60,/);
  assert.match(tsx, /background: DSH_BG_SOFT_GLASS,/);
  assert.match(tsx, /backdropFilter: 'blur\(8px\)',/);
  assert.match(tsx, /WebkitBackdropFilter: 'blur\(8px\)',/);
  assert.match(tsx, /position: 'sticky',\s*top: 0,\s*zIndex: 20,/);
  assert.match(tsx, /borderBottom: `1px solid \$\{DSH_SPLIT\}`/);
  assert.match(tsx, /fontSize: 18, fontWeight: 700,/);
  assert.match(tsx, /fontSize: 12, fontWeight: 400, color: DSH_TEXT_TERTIARY/);
  // 玻璃底与 soft 底同源共改守卫：DSH_BG_SOFT_GLASS 的 rgb 通道必须与
  // DSH_BG_SOFT 的 hex 通道一致（theme.ts 两值其一改动须同步另一值），
  // 且玻璃底必须保留透明度（实底即毛玻璃失效）
  const themeSrc = readFileSync(join(STATIC_ROOT, 'src', 'theme.ts'), 'utf8');
  const soft = themeSrc.match(/export const DSH_BG_SOFT = '#([0-9a-f]{6})'/);
  const glass = themeSrc.match(/export const DSH_BG_SOFT_GLASS = 'rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)'/);
  assert.ok(soft && glass, 'theme.ts 须同时声明 DSH_BG_SOFT(hex) 与 DSH_BG_SOFT_GLASS(rgba)');
  const hexToRgb = (h) => [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
  const softRgb = hexToRgb(soft[1]);
  assert.deepEqual(
    softRgb,
    [249, 250, 251],
    'DSH_BG_SOFT 漂移出用户定调 rgb(249,250,251)',
  );
  assert.deepEqual(
    [glass[1], glass[2], glass[3]].map(Number),
    softRgb,
    'DSH_BG_SOFT_GLASS 通道与 DSH_BG_SOFT 漂移（两值须同源共改）',
  );
  assert.ok(parseFloat(glass[4]) < 1, '玻璃底必须保留透明度（实底即毛玻璃失效）');
  // standalone chrome 接线守卫（2026-11-06 用户指令「菜单、标题栏、Fenix Harness
  // 标题背景 rgb(249,250,251)」+ 更正「标题栏保留毛玻璃」）：顶栏玻璃染色双档 +
  // 侧栏 soft 实底必须引用 theme.ts 常量单源、不得散落字面量；scroll 键漏配则
  // 滚动态顶栏回白染色（-fixed-header-scroll 换底）
  const headerGlass = themeSrc.match(/export const DSH_HEADER_GLASS = 'rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)'/);
  const headerGlassScroll = themeSrc.match(/export const DSH_HEADER_GLASS_SCROLL = 'rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)'/);
  assert.ok(headerGlass && headerGlassScroll, 'theme.ts 须声明 DSH_HEADER_GLASS 与 DSH_HEADER_GLASS_SCROLL');
  for (const m of [headerGlass, headerGlassScroll]) {
    assert.deepEqual(
      [m[1], m[2], m[3]].map(Number),
      softRgb,
      '顶栏玻璃染色通道与 DSH_BG_SOFT 漂移（soft 染色族须同源共改）',
    );
    assert.ok(parseFloat(m[4]) < 1, '顶栏玻璃染色必须保留透明度（毛玻璃生效前提）');
  }
  assert.match(themeSrc, /colorBgHeader: DSH_HEADER_GLASS,/);
  assert.match(themeSrc, /colorBgScrollHeader: DSH_HEADER_GLASS_SCROLL,/);
  assert.match(themeSrc, /colorMenuBackground: DSH_BG_SOFT,/);
  // 计数排版辅助（副标题随迁 tabular-nums 契约的页面侧入口）
  assert.match(tsx, /export function TitleBarNum/);
  assert.match(tsx, /fontVariantNumeric: 'tabular-nums'/);
  // 富标题 wrap 语义（mobile-detail-header-density 载体迁移）
  assert.match(tsx, /flexWrap: 'wrap'/);
});
test('迁移页 PageContainer 必须 title={false}+breadcrumbRender={false} 抑制路由名兜底页头与路由面包屑（双标题并存禁回潮）', () => {
  // pro-layout renderPageHeader 在无 title 且非 false 时从路由上下文兜底取
  // 路由名渲染自动页头；umi 布局插件还给多段路由注入 breadcrumbProps
  // （「项目 / fenixd」面包屑页头，title={false} 挡不住）；且 props 全空时
  // PageHeader 仍渲染 32px 空壳（.ant-page-header-no-children）——唯
  // pageHeaderRender={false} 走 renderPageHeader 的 return null 短路（3.2 实拍
  // 三连抓）。PagePlaceholder 兜底
  // 占位页按 specs 豁免条款保留路由名页头。
  const pages = [
    'overview/index', 'activities/index', 'help/index', 'settings/index',
    'projects/list', 'projects/detail', 'command-center/index',
  ];
  for (const page of pages) {
    const text = readFileSync(join(STATIC_ROOT, 'src', 'pages', page + '.tsx'), 'utf8');
    const opens = text.match(/<PageContainer[^>]*>/g) ?? [];
    assert.ok(opens.length > 0, page + ' 应仍有 PageContainer 本体');
    for (const open of opens) {
      assert.match(
        open,
        /<PageContainer\s+title=\{false\} breadcrumbRender=\{false\} pageHeaderRender=\{false\}>/,
        page + ' 的 PageContainer 须 title={false}+breadcrumbRender={false}：' + open,
      );
    }
  }
});
