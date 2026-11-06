// v2 页统一标题栏收编守卫（2026-11-06 用户指令三则：v2 页标题收编全站统一
// 标题栏控件、帮助页背景改白、帮助正文标题去重）。
//
// 四层钉死（pageChrome.test.mjs 源码扫描习语，注释一律先剥离——退役说明、
// 迁移注记里的「V2TitleBand」等字面量不得误命中，见 ops 方协同报备）：
// 1. 六页全经 V2Page titleBar 槽位声明 PageTitleBar，V2TitleBand 自画标题带
//    代码零残留（组件与配套 V2BackArrow 已退役删除）；
// 2. titleBar 渲染在 .v2-inner 之前——行壳位（embed 档；2026-11-06 二次指令后
//    移动端行壳位退役、标题随顶栏 HeaderSlot）标题带满宽贴顶、sticky 钉视口顶
//    依赖此结构，进 .v2-inner 会被 1400px 收窄 + 页顶内边距架空
//    （V2Page docstring 注释先于代码提及 .v2-inner，排序断言须在剥注释后做）；
// 3. help 页白底变体（variant="white" + `.v2-white` 仅改底色，1400px 居中列
//    不变，与 overview/projects 满宽变体区分）；
// 4. help 正文标题去重：DocPane 不渲染自动 doc.title——后端 title 本就从
//    markdown 首个一级标题解析（help_routes._help_doc_title），双显即同文重复。
// 运行：cd core/dashboard/static && node --test tests/v2TitleBarGuard.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const STATIC_ROOT = join(import.meta.dirname, '..');
const readV2 = (name) => readFileSync(join(STATIC_ROOT, 'src', 'pages', 'v2', name), 'utf8');
// 注释剥离（pageChrome 同款）：块注释 + 行注释移除后再做字面量/顺序断言
const stripComments = (text) => text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');

const V2_PAGES = [
  'overview.tsx',
  'projectDetail.tsx',
  'specDetail.tsx',
  'settings.tsx',
  'help.tsx',
  'ops.tsx',
];

test('六页全经 V2Page titleBar 槽位声明 PageTitleBar（自画标题带代码零残留）', () => {
  for (const page of V2_PAGES) {
    const code = stripComments(readV2(page));
    assert.ok(code.includes('titleBar={'), `${page} 应经 V2Page titleBar 槽位声明标题栏`);
    assert.ok(code.includes('<PageTitleBar'), `${page} 应声明 PageTitleBar`);
    assert.ok(!code.includes('V2TitleBand'), `${page} 不得残留 V2TitleBand 代码引用`);
  }
  // 共享原语侧：V2TitleBand / V2BackArrow 已退役删除（六页迁完后收尾，勿回填）
  const shared = stripComments(readV2('shared.tsx'));
  assert.ok(!shared.includes('function V2TitleBand'), 'shared.tsx 的 V2TitleBand 应已删除');
  assert.ok(!shared.includes('function V2BackArrow'), 'shared.tsx 的 V2BackArrow 应已删除');
});

test('V2Page titleBar 渲染在 .v2-inner 之前（行壳位满宽贴顶结构单源）', () => {
  const shared = stripComments(readV2('shared.tsx'));
  const titleBarAt = shared.indexOf('{titleBar}');
  const innerAt = shared.indexOf('v2-inner');
  assert.ok(titleBarAt >= 0, 'V2Page 应渲染 {titleBar}');
  assert.ok(
    innerAt > titleBarAt,
    '{titleBar} 须先于 .v2-inner（进 inner 会被 1400px 收窄 + 页顶内边距架空，sticky 跳位）',
  );
});

test('帮助页白底变体：variant="white" + .v2-white 规则（仅改底色不动居中列）', () => {
  const help = readV2('help.tsx');
  assert.match(help, /variant="white"/, 'help 页应启用白底变体');
  const less = readV2('v2.less');
  assert.match(less, /\.v2-page\.v2-white[\s\S]{0,120}background:\s*#ffffff/, '.v2-white 应改页底纯白');
  // white 变体与 overview/projects 满宽变体的区分点：不改 .v2-inner（1400px 居中列保留）
  assert.ok(!less.includes('.v2-page.v2-white .v2-inner'), '.v2-white 不应覆写 .v2-inner（居中列不变）');
});

test('帮助正文标题去重：DocPane 不渲染自动 doc.title（与正文 H1 同文双显）', () => {
  const help = stripComments(readV2('help.tsx'));
  assert.ok(!help.includes('{doc.title}'), 'DocPane 不得渲染自动 doc.title——后端 title 本就从 markdown 首个一级标题解析');
  assert.match(help, /\{doc\.content\}/, '正文仍渲染 doc.content（markdown 自身 H1 为唯一标题）');
});
