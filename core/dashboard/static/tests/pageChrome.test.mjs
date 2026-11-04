// 页面 chrome 去冗余守卫（2026-11-04「内容区 40px 留白 + 包裹卡边框」治理回归守卫）。
//
// 治理内容（帮助页取证推广全菜单）：
// - PageContainer 内容区左右留白 pro-layout 默认 40px → 15（2026-11-04 用户二次
//   裁决：首版齐平 0 过紧，回撤窄边距）：theme.ts dshLayoutToken 单源（app.tsx
//   layout 配置 token 键消费），页头标题行同 token 自动对齐；<768 窄屏 12px 由
//   global.less 既有覆盖规则接管，不受影响。注意 pro-layout getLayoutDesignToken
//   的缺省回填是 `x || 40`，0 会被吞——实际生效靠其尾部
//   `...finalDesignTokens.pageContainer` 展开，值改动前须复核该合并行为。
// - PageContainer 内容区 .ant-card-bordered 统一去边框（global.less #root 前缀
//   规则）：白底页面上包裹卡边框属冗余 chrome，对齐宿主 dsh web 平铺风格。
//
// 零依赖 node:test 源码扫描（同 darkSeedBgToken.test.mjs 习语）；视觉行为由
// `npm run build` 与浏览器冒烟覆盖，本文件锁定配置单源与接线。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { dshLayoutToken } from '../src/theme.ts';

const STATIC_ROOT = join(import.meta.dirname, '..');

test('内容区左右留白单源=15px：pro-layout 缺省 40px 不得回潮', () => {
  assert.equal(dshLayoutToken.pageContainer.paddingInlinePageContainerContent, 15);
});

test('app.tsx layout 配置必须消费 dshLayoutToken（漏接线则 40px 回潮）', () => {
  const text = readFileSync(join(STATIC_ROOT, 'src', 'app.tsx'), 'utf8');
  assert.match(text, /token:\s*dshLayoutToken/);
});

test('global.less 必须保留内容区卡片去边框规则（页级作用域，Modal/大屏例外域不受影响）', () => {
  const text = readFileSync(join(STATIC_ROOT, 'src', 'global.less'), 'utf8');
  assert.match(
    text,
    /#root \.ant-pro-page-container \.ant-card\.ant-card-bordered \{\s*border: 0;/,
  );
});

test('概览统计卡行必须保留边框（页级去边框规则的定向豁免；组件侧 variant=outlined）', () => {
  const less = readFileSync(join(STATIC_ROOT, 'src', 'global.less'), 'utf8');
  // 豁免规则须在页级去边框规则之后（同特异性靠后置生效）
  const removalAt = less.indexOf('#root .ant-pro-page-container .ant-card.ant-card-bordered');
  const exemptAt = less.indexOf('#root .overview-intro-row .ant-card.ant-card-bordered');
  assert.ok(removalAt !== -1 && exemptAt > removalAt);
  assert.match(
    less,
    /#root \.overview-intro-row \.ant-card\.ant-card-bordered \{\s*border: 1px solid rgba\(0, 0, 0, 0\.1\);/,
  );
  const tsx = readFileSync(
    join(STATIC_ROOT, 'src', 'pages', 'overview', 'components', 'IntroduceRow.tsx'),
    'utf8',
  );
  assert.match(tsx, /<Card\s+variant="outlined"/);
  assert.doesNotMatch(tsx, /variant="borderless"/);
});

test('global.less 必须保留页头标题行避让规则（侧栏折叠钮悬浮于内容区左缘标题带内）', () => {
  const text = readFileSync(join(STATIC_ROOT, 'src', 'global.less'), 'utf8');
  assert.match(
    text,
    /#root \.ant-pro-page-container > \.ant-page-header \{\s*padding-inline: 24px;\s*padding-block-end: 0;/,
  );
});

test('设置页隐形包裹卡 body 左右内边距必须回收（该页无边框可去，24px body 是主要留白面）', () => {
  const text = readFileSync(join(STATIC_ROOT, 'src', 'global.less'), 'utf8');
  assert.match(text, /#root \.settings-page > \.ant-card-body \{\s*padding: 24px 0;/);
});

test('设置页面板卡头底线必须去除（body 顶缘唯一可见线源；灰底双档已承担分隔）', () => {
  const text = readFileSync(join(STATIC_ROOT, 'src', 'global.less'), 'utf8');
  assert.match(
    text,
    /#root \.settings-page \.ant-card\.ant-card-bordered > \.ant-card-head \{\s*border-bottom: 0;/,
  );
});

test('项目页包裹卡 body 内边距必须收紧到 8px（类名单源在 list.tsx 包裹卡上）', () => {
  const less = readFileSync(join(STATIC_ROOT, 'src', 'global.less'), 'utf8');
  assert.match(less, /#root \.projects-page > \.ant-card-body \{\s*padding: 8px;/);
  const tsx = readFileSync(join(STATIC_ROOT, 'src', 'pages', 'projects', 'list.tsx'), 'utf8');
  assert.match(tsx, /<Card variant="borderless" className="projects-page">/);
});

test('设置页定高滚动接线必须齐全：卡高 calc 常量 + 卡体 flex 传导 + 右栏 overflowY（纯 CSS，禁脚本算高）', () => {
  const less = readFileSync(join(STATIC_ROOT, 'src', 'global.less'), 'utf8');
  assert.match(
    less,
    /\.ant-design-pro:not\(\.screen-xs\):not\(\.screen-sm\)\s+\.settings-page\s*>\s*\.ant-card-body \{\s*height: 100%;\s*display: flex;\s*flex-direction: column;/,
  );
  const tsx = readFileSync(join(STATIC_ROOT, 'src', 'pages', 'settings', 'index.tsx'), 'utf8');
  // unified-page-title-bar 后 PageContainer 页头摘除：standalone = 顶栏 56；
  // embed = 顶栏隐藏、统一标题行行壳位 48。旧双档 68/124（含页头）见 git 历史
  assert.match(tsx, /const SETTINGS_FRAME_OFFSET = isEmbedMode\(\) \? 48 : 56;/);
  assert.match(tsx, /calc\(100vh - \$\{SETTINGS_FRAME_OFFSET\}px\)/);
  assert.match(tsx, /overflowY: 'auto'/);
});

test('页面内容区卡片阴影必须移除（antd v6 卡默认 0.05 微阴影=白底上的隐形边）', () => {
  const less = readFileSync(join(STATIC_ROOT, 'src', 'global.less'), 'utf8');
  assert.match(
    less,
    /#root \.ant-pro-page-container \.ant-card \{\s*box-shadow: none;/,
  );
});

test('设置页面板 body 内边距禁止归零（padding 0 曾使表单网格/计费子行贴死面板四缘，2026-11-04 实证布局散架已回退）', () => {
  const less = readFileSync(join(STATIC_ROOT, 'src', 'global.less'), 'utf8');
  assert.doesNotMatch(
    less,
    /#root \.settings-page \.ant-card\.ant-card-bordered > \.ant-card-body \{\s*padding: 0;/,
  );
});

test('设置页滚动条贴缘三件套：卡体负右外边距（-15 强耦合 dshLayoutToken）+ 卡体块尾归零 + 表单右 16px', () => {
  const less = readFileSync(join(STATIC_ROOT, 'src', 'global.less'), 'utf8');
  assert.match(
    less,
    /\.ant-design-pro:not\(\.screen-xs\):not\(\.screen-sm\)\s+\.settings-page \{\s*margin-right: -15px;/,
  );
  assert.match(
    less,
    /\.ant-design-pro:not\(\.screen-xs\):not\(\.screen-sm\)\s+\.settings-page\s*>\s*\.ant-card-body \{[^}]*padding-block-end: 0;/,
  );
  assert.match(less, /#root \.settings-page \.ant-form \{\s*padding-right: 16px;/);
});

test('设置页面板直角化：卡根与卡头 border-radius 0（圆角灰底剪影即「圆角边框」来源）', () => {
  const less = readFileSync(join(STATIC_ROOT, 'src', 'global.less'), 'utf8');
  assert.match(
    less,
    /#root \.settings-page \.ant-card\.ant-card-bordered \{\s*background-color: #f6f6f6;[^}]*border-radius: 0;/,
  );
  assert.match(
    less,
    /#root \.settings-page \.ant-card\.ant-card-bordered > \.ant-card-head \{\s*background-color: #efefef;\s*border-radius: 0;/,
  );
});

test('设置页页头 heading 12px 块尾补偿必须保持退役（PageContainer 页头已摘除，补偿对象不复存在）', () => {
  // unified-page-title-bar 2.2：页头消失后 12px padding-block-end 补偿随页头
  // 一起退役（global.less 保留退役说明注释）；规则回潮会在无页头的现实下
  // 悬空空转，且 :has 选择器依赖 .ant-page-header-heading 元素不再渲染
  assert.doesNotMatch(
    readFileSync(join(STATIC_ROOT, 'src', 'global.less'), 'utf8'),
    /\.ant-page-header-heading \{\s*padding-block-end: 12px;/,
  );
});

test('菜单选中底统一=黑 4% alpha（与 ProLayout 侧栏看齐；冷灰 10% 在内层菜单显著偏深）', () => {
  const theme = readFileSync(join(STATIC_ROOT, 'src', 'theme.ts'), 'utf8');
  assert.match(theme, /export const DSH_MENU_SELECTED_BG = 'rgba\(0, 0, 0, 0\.04\)';/);
  assert.match(theme, /itemSelectedBg: DSH_MENU_SELECTED_BG,/);
  assert.match(theme, /itemActiveBg: 'rgba\(0, 0, 0, 0\.06\)'/);
  const help = readFileSync(join(STATIC_ROOT, 'src', 'pages', 'help', 'index.tsx'), 'utf8');
  assert.match(help, /background: DSH_MENU_SELECTED_BG/);
  assert.doesNotMatch(help, /DSH_INTERACTIVE_ACTIVE/);
});
