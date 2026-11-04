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

test('壳位判定收敛在组件内：embed 或 <768 行壳位，页面侧零环境分支', () => {
  const tsx = readComponent();
  // 判定单源：isEmbedMode() || isMobile 收敛在 PageTitleBar 内部
  assert.match(tsx, /const rowSlot = isEmbedMode\(\) \|\| isMobile;/);
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

test('行壳位形态锚点：48px 白底 DSH_SPLIT 底缘细线 + 同构槽位件（theme.ts 单源配色）', () => {
  const tsx = readComponent();
  assert.match(tsx, /minHeight: 48,/);
  assert.match(tsx, /borderBottom: `1px solid \$\{DSH_SPLIT\}`/);
  assert.match(tsx, /fontSize: 18, fontWeight: 700,/);
  assert.match(tsx, /fontSize: 12, fontWeight: 400, color: DSH_TEXT_TERTIARY/);
  // 计数排版辅助（副标题随迁 tabular-nums 契约的页面侧入口）
  assert.match(tsx, /export function TitleBarNum/);
  assert.match(tsx, /fontVariantNumeric: 'tabular-nums'/);
  // 富标题 wrap 语义（mobile-detail-header-density 载体迁移）
  assert.match(tsx, /flexWrap: 'wrap'/);
});
