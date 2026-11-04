// mermaid 图内字号守卫（帮助页 2026-11-03「图与字体太大」修复回归守卫）。
//
// 根因：mermaid 顶层 fontSize 默认 16；sequence 图渲染时 db.init() →
// setConf(getConfig()) 级联 `actorFontSize = noteFontSize = messageFontSize =
// 顶层 fontSize`，sequence 子键的单独设置被覆写——单独设 14 无效，全族渲染
// 16px，大于 Markdown 正文的 14px。修复 = 顶层 fontSize 与 themeVariables.fontSize
// 双层同设 14（A/B 实测：无顶层 16px / 有顶层 14px）。
//
// 零依赖 node:test 直载常量模块（同 harnessBrand.test.mjs 习语；Node ≥22.18）。
// 渲染视觉行为由浏览器冒烟覆盖，本文件锁定配置单源。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { MERMAID_FONT_SIZE, MERMAID_INIT_CONFIG } from '../src/pages/help/mermaidInit.ts';
import { DSH_FONT_FAMILY } from '../src/theme.ts';

const BODY_FONT_PX = 14; // help 页正文容器 fontSize（index.tsx），图内字号与之对齐

test('顶层 fontSize 必设：sequence 级联取顶层值，缺省 16 即全族 16px', () => {
  assert.equal(MERMAID_INIT_CONFIG.fontSize, BODY_FONT_PX);
});

test('顶层 fontFamily 必设且=正文单源：mermaid 默认栈同 px 观感大一号（字体族裁决实验）', () => {
  assert.equal(MERMAID_INIT_CONFIG.fontFamily, DSH_FONT_FAMILY);
});

test('themeVariables.fontSize 必设：flowchart/state 等 label 直接消费，且与正文同值', () => {
  assert.equal(MERMAID_INIT_CONFIG.themeVariables.fontSize, `${BODY_FONT_PX}px`);
});

test('sequence 子键同值保留：级联被上游移除时不反弹回 message 缺省 16', () => {
  const seq = MERMAID_INIT_CONFIG.sequence;
  for (const key of ['actorFontSize', 'messageFontSize', 'noteFontSize']) {
    assert.equal(seq[key], BODY_FONT_PX, `sequence.${key} 应为 ${BODY_FONT_PX}`);
  }
});

test('MERMAID_FONT_SIZE 与两层配置一致（单源不漂移）', () => {
  assert.equal(MERMAID_FONT_SIZE, MERMAID_INIT_CONFIG.fontSize);
  assert.equal(MERMAID_FONT_SIZE, Number.parseInt(MERMAID_INIT_CONFIG.themeVariables.fontSize, 10));
});
