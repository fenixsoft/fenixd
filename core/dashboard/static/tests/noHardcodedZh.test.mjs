// 中文硬编码抽查守卫（add-framework-i18n-zh-en 3.6 / design D4）。
//
// 对已抽取页面的代表文件断言 JS 字符串字面量无中文字符——防新增硬编码回潮
// （全站无残留以逐页 playwright en 档巡检兜底，不做全仓静态穷举：成本高误报多）。
// 豁免面：注释（// 与 /* */ 先剥再扫）、src/locales/ 文案目录本身、动态数据
// 文本（后端返回数据不经源码字面量）。
// 抽查清单覆盖每页至少一文件（overview/projects/settings/activities/
// command-center/help + 全局组件 + utils）。
// 运行：cd core/dashboard/static && node --test tests/noHardcodedZh.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const SRC_ROOT = new URL('../src/', import.meta.url);

/** 抽查清单：每页至少一代表文件 + 全局组件 + utils 展示映射。
 *
 * 豁免登记（抽取批核查结论，add-framework-i18n-zh-en 3.5/3.6）：
 * - utils/runVisual.ts：runVisual.test.mjs node 直载断言 AGENT_LABEL 表中文值
 *   （直载模块不能 import '@umijs/max'，改键映射必红）——该文件不抽（中文
 *   标签为既有契约面），不入抽查清单；
 * - utils/tokens.ts、utils/llmHealth.ts、claude-msg/chatFormatting.ts 等：
 *   同因（node 直载/esbuild 测试打包链约束），抽取批登记豁免；
 * - markdown-shared.tsx：中文为知识表头指纹匹配键（逻辑用途非展示文案）。
 */
const AUDIT_FILES = [
  'pages/overview/index.tsx',
  'pages/projects/index.tsx',
  'pages/settings/index.tsx',
  'pages/activities/index.tsx',
  'pages/command-center/index.tsx',
  'pages/help/index.tsx',
  'components/PageTitleBar.tsx',
  'hooks/useAlertAdjudication.tsx',
];

const CJK = /[一-鿿㐀-䶿豈-﫿]/;

/** 剥注释后扫描字符串字面量中的中文（模板字符串/单双引号）。 */
function findChineseInLiterals(src) {
  // 1) 剥行注释与块注释（字符串内 // 与 /* 不误伤：先按字符串状态机扫描）
  const stripped = stripComments(src);
  // 2) 扫描字符串字面量（单引号/双引号/模板字符串），收集含中文的片段
  const hits = [];
  let i = 0;
  let quote = null;
  let start = -1;
  while (i < stripped.length) {
    const ch = stripped[i];
    const prev = i > 0 ? stripped[i - 1] : '';
    if (quote) {
      if (ch === '\\' && i + 1 < stripped.length) {
        i += 2;
        continue;
      }
      if (ch === quote) {
        const literal = stripped.slice(start + 1, i);
        if (CJK.test(literal)) {
          const line = stripped.slice(0, start).split('\n').length;
          hits.push({ line, literal: literal.slice(0, 80) });
        }
        quote = null;
      }
      i += 1;
      continue;
    }
    if (ch === "'" || ch === '"' || ch === '`') {
      quote = ch;
      start = i;
    }
    i += 1;
  }
  return hits;
}

/** 字符串感知的注释剥离（避免把字符串内的 // 当注释剥坏字面量）。 */
function stripComments(src) {
  let out = '';
  let i = 0;
  let quote = null;
  while (i < src.length) {
    const ch = src[i];
    const next = src[i + 1];
    if (quote) {
      out += ch;
      if (ch === '\\') {
        out += next ?? '';
        i += 2;
        continue;
      }
      if (ch === quote) quote = null;
      i += 1;
      continue;
    }
    if (ch === "'" || ch === '"' || ch === '`') {
      quote = ch;
      out += ch;
      i += 1;
      continue;
    }
    if (ch === '/' && next === '/') {
      while (i < src.length && src[i] !== '\n') i += 1;
      continue;
    }
    if (ch === '/' && next === '*') {
      i += 2;
      while (i < src.length && !(src[i] === '*' && src[i + 1] === '/')) i += 1;
      i += 2;
      continue;
    }
    out += ch;
    i += 1;
  }
  return out;
}

/** 逐字面量豁免登记（逻辑用途非展示文案，抽取批核查结论）：
 * - activities/index.tsx resultPill：v1 关键词配色兜底对后端自由文本 result 做
 *   includes 匹配——中文词是匹配键（匹配后端数据），不是渲染文案。
 */
const LITERAL_EXEMPTS = {
  'pages/activities/index.tsx': ['成功', '失败', '处理'],
};

for (const rel of AUDIT_FILES) {
  test(`无中文硬编码字符串字面量：src/${rel}`, async () => {
    let src;
    try {
      src = await readFile(new URL(rel, SRC_ROOT), 'utf8');
    } catch {
      // 文件不在（代表清单与仓库现实漂移）：显式失败提示清单维护，不放行
      assert.fail(`抽查清单文件不存在：src/${rel}——请更新 noHardcodedZh.test.mjs AUDIT_FILES`);
    }
    const exempt = LITERAL_EXEMPTS[rel] || [];
    const hits = findChineseInLiterals(src).filter((h) => !exempt.includes(h.literal));
    assert.deepEqual(
      hits,
      [],
      `发现 ${hits.length} 处字符串字面量含中文（应迁入 src/locales/ 目录并经 intl 接线）：\n` +
        hits.map((h) => `  L${h.line}: ${JSON.stringify(h.literal)}`).join('\n'),
    );
  });
}
