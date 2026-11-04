// 帮助页滚动布局守卫（2026-11-04 用户指令：内容滚动条下沉到正文 div，目录
// 不随页面滚动；正文 padding-top 24 → 0）。
//
// 滚动下沉的前提是整卡定高：calc(100vh - 页框偏移) 纯 CSS（用户明确否掉
// JS 测高脚本——偏移校准：standalone 顶栏 56（unified-page-title-bar 后
// PageContainer 页头已摘除，标题进顶栏插槽）；embed 全局顶栏隐藏、统一
// 标题行为内容区首行 48）。不取 pageChrome.ts 常数（项目详情页 Tabs 版
// 页框，本页无 Tabs 不通用）。
//
// 零依赖 node:test 源码扫描（同 pageChrome.test.mjs 习语）；视觉行为由
// `npm run build` 与浏览器冒烟覆盖，本文件锁定接线与形态不回潮。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const STATIC_ROOT = join(import.meta.dirname, '..');
const readHelpPage = () => readFileSync(join(STATIC_ROOT, 'src', 'pages', 'help', 'index.tsx'), 'utf8');

test('正文 div 必须自带滚动条（overflowY auto）：滚动不落在页面上', () => {
  // 正文容器 = flex:1 + minWidth:0 的那个 div；padding 与 overflow 锁同一处声明
  assert.match(
    readHelpPage(),
    /flex: 1, minWidth: 0, padding: '0 32px 24px'.*overflowY: 'auto'/,
  );
});

test('正文 padding-top 必须归 0（2026-11-04 用户指令 24 → 0；底部 24 呼吸保留）', () => {
  assert.match(readHelpPage(), /padding: '0 32px 24px'/);
  // 旧值不得残留（两值简写 '24px 32px' 或含顶部 24 的写法都算回潮）
  assert.doesNotMatch(readHelpPage(), /padding: '24px 32px'/);
});

test('目录列必须有自滚兜底（页面不滚后长目录若无自滚会被定高裁掉）', () => {
  const text = readHelpPage();
  // 目录列特征：width 240 + borderRight；overflowY 与之同处一块声明
  assert.match(
    text,
    /width: 240,[\s\S]{0,200}?borderRight: '1px solid var\(--ant-color-border-secondary\)'[\s\S]{0,200}?overflowY: 'auto'/,
  );
});

test('整卡定高必须是纯 CSS calc(100vh - 偏移)，双模式偏移实测值锁定', () => {
  const text = readHelpPage();
  // calc 接线在 flex 行 style 上
  assert.match(text, /height: `calc\(100vh - \$\{HELP_FRAME_OFFSET\}px\)`/);
  // 双模式偏移 = 卡片上方页框占用：standalone 顶栏 56（PageContainer 页头已
  // 摘除）；embed 顶栏隐藏、统一标题行行壳位 48（卡片贴视口底后文档流恰 =
  // 100vh，无底带、无页面级滚动条）。校准值改动时须同步复核两种模式
  // （standalone 1440×900 卡底贴视口底）
  assert.match(text, /isEmbedMode\(\) \? 48 : 56/);
  // JS 测高方案不得回潮（用户明确否掉）：flex 行不挂 ref 测高
  assert.doesNotMatch(text, /getBoundingClientRect\(\)\.top \+ window\.scrollY/);
});

test('正文滚动条贴窗口右缘：包裹卡右缘负外边距吃掉内容区右留白（单源取 token，勿硬编码）', () => {
  const text = readHelpPage();
  assert.match(
    text,
    /marginInlineEnd: -dshLayoutToken\.pageContainer\.paddingInlinePageContainerContent/,
  );
});
