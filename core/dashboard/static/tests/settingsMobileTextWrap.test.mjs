// 设置页移动端文本断行守卫（2026-11-07 质量页签 390px 溢出治理回归守卫）。
//
// 根因：label-note 注解内是下划线连接的长英文配置键 token（如
// admin.code_review_fix.severity_batch_gate_enabled，44 字符无自然断点），
// 缺省 overflow-wrap:normal 下整 token 伸出卡区（doc.scrollWidth 411 > 390）。
// 修复：global.less 移动作用域（screen-xs ∪ screen-sm = <768，与 useIsMobile
// 对齐的既有约定）对四类文本载体放开 overflow-wrap:anywhere——表格单元格
// 不在列（宽表走容器内横向滚动的既有形态）；PC 端规则不命中零影响。
//
// 零依赖 node:test 源码扫描（同 pageChrome.test.mjs 习语）；视觉行为由
// `npm run build` 与浏览器冒烟覆盖，本文件锁定规则存在与作用域接线。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const STATIC_ROOT = join(import.meta.dirname, '..');
const readLess = () => readFileSync(join(STATIC_ROOT, 'src', 'global.less'), 'utf8');

test('设置页移动端断行规则存在且覆盖四类文本载体（label-note 溢出治理）', () => {
  const less = readLess();
  const carriers = [
    '.settings-page .label-note',
    '.settings-page .switch-inline-label',
    '.settings-page .ant-form-item-label label',
    '.settings-page .ant-typography',
  ];
  for (const sel of carriers) {
    const re = new RegExp(
      `#root :is\\(\\.screen-xs, \\.screen-sm\\) ${sel.replaceAll('.', '\\.').replace(/\s+/g, '\\s+')}[,\\s]*[\\s\\S]*?overflow-wrap:\\s*anywhere`,
    );
    assert.match(
      less,
      re,
      `global.less 移动作用域必须含 ${sel} 的 overflow-wrap:anywhere（配置键长 token 窄屏溢出，勿回退）`,
    );
  }
});

test('断行规则必须挂在 <768 移动作用域（PC ≥768 端零影响）', () => {
  const less = readLess();
  // 规则块整体前置移动断点作用域：抽出含 overflow-wrap:anywhere 的设置页规则段核对
  const block = less.slice(less.indexOf('.settings-page .label-note'), less.indexOf('overflow-wrap: anywhere'));
  assert.match(block, /:is\(\.screen-xs, \.screen-sm\)/);
});

test('表格单元格不参与 anywhere 断行（宽表保持容器内横向滚动形态）', () => {
  const less = readLess();
  const block = less.slice(
    less.indexOf('设置页窄屏断行兜底'),
    less.indexOf('概览页统计卡移动端优化'),
  );
  assert.doesNotMatch(block, /ant-table|\.ant-table-cell/);
});
