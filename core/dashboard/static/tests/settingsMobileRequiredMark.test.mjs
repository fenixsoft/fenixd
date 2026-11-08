// 设置页移动端必填星号同行守卫（2026-11-07 审批页签红点独占一行治理回归守卫）。
//
// 根因：移动端 label 块化（既有 <768 规则）后，复合 label（ApprovalModePanel
// 四组「外层 block 包装 span > 名称 block span + 说明 block Text」的 required
// 项）的 block 首子把 ::before 星号（行内盒）甩成独占一行——红点单独占一行。
// 修复：global.less 移动作用域把 .ant-form-item-required 的 ::before 拎出文档
// 流（absolute 钉名称首行左缘），required label 留 padding-left 腾位；选填
// label 不受影响；PC（≥768）inline-flex 布局原样。
//
// 零依赖 node:test 源码扫描（同 pageChrome.test.mjs 习语）；视觉行为由
// `npm run build` 与浏览器冒烟覆盖，本文件锁定规则存在与作用域接线。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const STATIC_ROOT = join(import.meta.dirname, '..');
const readLess = () => readFileSync(join(STATIC_ROOT, 'src', 'global.less'), 'utf8');

test('必填星号规则挂在移动作用域且拎出文档流（红点不得独占一行回归）', () => {
  const less = readLess();
  const anchor = less.indexOf('.settings-page .ant-form-item-required');
  assert.notEqual(anchor, -1, 'global.less 必须含设置页移动端 .ant-form-item-required 规则');
  const block = less.slice(anchor, less.indexOf('}', anchor) + 40);
  assert.match(block, /:is\(\.screen-xs, \.screen-sm\)/, '规则必须挂在 <768 移动作用域（PC 零影响）');
  assert.match(block, /position:\s*relative/);
  assert.match(block, /padding-left:\s*12px/);
});

test('::before 星号必须 absolute 钉左缘（static 会回到行内流被 block 首子甩独行）', () => {
  const less = readLess();
  assert.match(
    less,
    /#root :is\(\.screen-xs, \.screen-sm\) \.settings-page \.ant-form-item-required::before\s*\{[^}]*position:\s*absolute[^}]*left:\s*0/,
  );
});
