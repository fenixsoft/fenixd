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
 * - utils/tokens.ts、utils/llmHealth.ts：i18n 修复轮 batch-A 起已迁 intl 目录
 *   （utils/intlText.ts shim 三语境回落，node 直载/esbuild/raw 均安全），
 *   转入抽查清单（豁免登记撤销）；
 * - utils/runVisual.ts：i18n 修复轮 batch-C 起已迁 intl 目录（原豁免理由
 *   「node 直载不能 import '@umijs/max'」经 intlText shim 解除——直载回落
 *   zh 目录原文，runVisual.test.mjs 断言零改动），转入抽查清单（豁免登记
 *   撤销）；
 * - markdown-shared.tsx：中文为知识表头指纹匹配键（逻辑用途非展示文案）。
 * - markdown-shared.tsx：中文为知识表头指纹匹配键（逻辑用途非展示文案），
 *   i18n 修复轮 batch-G 起转入正式逐字面量豁免登记（LITERAL_EXEMPTS）；
 * - claude-msg 组件族（runEvents/toolGrouping/chatFormatting 直载链 + 各渲染
 *   组件）：i18n 修复轮 batch-G 起已迁 intl 目录（直载链经 intlText zh 回落
 *   保持既有中文断言零改动），转入抽查清单（原「不抽」豁免登记撤销）。
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
  // i18n 修复轮 batch-P：projects 工作台域页面级代表文件
  'pages/projects/detail.tsx',
  'pages/projects/list.tsx',
  'pages/projects/components/RegressionTab.tsx',
  // i18n 修复轮 batch-S：settings 域面板迁移代表（页面级抽样，非全量清单）
  'pages/settings/components/MiscSettingsPanel.tsx',
  'pages/settings/components/SuggestedImprovementsPanel.tsx',
  'pages/settings/components/QuickAssignModal.tsx',
  'pages/settings/components/SystemPanel.tsx',
  // i18n 修复轮 batch-A：activities+services 域代表（告警共享组件、更新面板、
  // 处置链面板、Admin run 弹窗）+ 服务层/utils 用户可见串迁移代表
  'components/alert-shared.tsx',
  'pages/activities/components/UpdatePanel.tsx',
  'pages/activities/components/ChainPanel.tsx',
  'pages/activities/components/AdminRunModal.tsx',
  'services/dashboard.ts',
  'utils/duration.ts',
  'utils/tokens.ts',
  'utils/llmHealth.ts',
  // i18n 修复轮 batch-C：command-center 域中文 chrome 迁移代表
  'pages/command-center/shared.ts',
  'pages/command-center/ExecutionLedger.tsx',
  'pages/command-center/OrgGrid.tsx',
  'pages/command-center/PipelineBoard.tsx',
  'utils/runVisual.ts',
  // i18n 修复轮 batch-G：全局组件域（HookManager + claude-msg 组件族渲染/分组/
  // 格式化链 + markdown-shared 匹配键 + 弹窗最大化 + 新会话钮）
  'components/HookManager.tsx',
  'components/claude-msg/runEvents.ts',
  'components/claude-msg/ClaudeOutputPane.tsx',
  'components/claude-msg/MessageItem.tsx',
  'components/claude-msg/Markdown.tsx',
  'components/claude-msg/ToolCard.tsx',
  'components/claude-msg/Reasoning.tsx',
  'components/claude-msg/ToolGroupContainer.tsx',
  'components/claude-msg/toolGrouping.ts',
  'components/claude-msg/chatFormatting.ts',
  'components/markdown-shared.tsx',
  'components/useMaximizeModal.tsx',
  'components/DshNewSessionButton.tsx',
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
 * - projects/detail.tsx requestHostNewSession：写回 host 的新会话引导 prompt
 *   （载荷数据非渲染文案）。
 * - services/dashboard.ts（i18n 修复轮 batch-A）：console 留痕串两条（_setBundleRev
 *   测试钩子告警、bundle 热更新刷新日志）+ 编程契约守卫消息（project 必填，
 *   面向开发者非终端用户），均非 UI 展示文案。
 * - components/HookManager.tsx（i18n 修复轮 batch-G）：console.error 留痕串一条
 *   （保存失败开发者诊断，非 UI 展示文案）。
 * - components/markdown-shared.tsx（i18n 修复轮 batch-G 转正式登记）：知识表头
 *   指纹匹配键五个（表格解析按表头中文识别知识表，匹配键非展示文案）。
 */
const LITERAL_EXEMPTS = {
  'pages/activities/index.tsx': ['成功', '失败', '处理'],
  'pages/projects/detail.tsx': ['对于 ${spec} SPEC：'],
  'services/dashboard.ts': [
    '[dashboard] _setBundleRev 是测试钩子（生产勿调用）：生产构建中被调用，已放行并留痕',
    '[dashboard] 检测到前端已更新（X-Bundle-Rev ${bundleRevBaseline} → ${rev}），整页刷新加载新版本',
    '${fnName}: project 必填（后端对缺 project 恒 400）',
  ],
  'components/HookManager.tsx': ['[HookManager] 保存 hook 失败'],
  'components/markdown-shared.tsx': ['编号', '能力数量', '能力页', '简介', '摘要'],
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
