// 帮助页滚动布局守卫（2026-11-05 用户指令两连定调：①全站滚动条范围统一——
// 滚动条跨标题区域，页面纵向滚动统一走文档级，同概览/项目/运维记录口径，
// 原 2026-11-04「整卡定高 + 正文 div 自滚」形态整体退役；②菜单/目录不能
// 滚走——目录列本体 sticky 钉在标题带下缘，长目录自滚兜底。本文件锁定
// 上述形态不回潮）。
//
// 零依赖 node:test 源码扫描（同 pageChrome.test.mjs 习语）；视觉行为由
// `npm run build` 与浏览器冒烟覆盖。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const STATIC_ROOT = join(import.meta.dirname, '..');
const readHelpPage = () => readFileSync(join(STATIC_ROOT, 'src', 'pages', 'help', 'index.tsx'), 'utf8');

test('整卡定高形态不得回潮：无页框偏移常数、无视口算高 height 链', () => {
  const text = readHelpPage();
  // 定高常数（旧双档 56/60）与高度链已随文档级滚动统一退役，见 git 历史；
  // 视口 calc 只允许出现在目录 sticky 的 maxHeight（钉住高度预算），任何
  // height: calc(100vh) 高度链回潮即违规
  assert.doesNotMatch(text, /const HELP_FRAME_OFFSET/);
  assert.doesNotMatch(text, /height: `calc\(100vh/);
  assert.match(text, /maxHeight: `calc\(100vh - \$\{HELP_TOC_STICKY_TOP\}px - 16px\)`/);
  // JS 测高方案不得回潮（用户明确否掉）
  assert.doesNotMatch(text, /getBoundingClientRect\(\)\.top \+ window\.scrollY/);
});

test('目录列必须 sticky 钉住不随页面滚走（2026-11-05 用户指令「菜单/目录不能滚走」）', () => {
  const text = readHelpPage();
  // 目录列 = width 240 外壳（撑满列高承分隔线）+ 本体 sticky（钉住偏移双档 +
  // 长目录自滚兜底 overflowY，同块声明）
  assert.match(
    text,
    /width: 240,[\s\S]{0,200}?position: 'sticky',\s*top: HELP_TOC_STICKY_TOP,[\s\S]{0,200}?overflowY: 'auto'/,
  );
  // 钉住偏移双档实测值锁定：standalone 顶栏 56 / embed 行壳位 60
  assert.match(text, /const HELP_TOC_STICKY_TOP = isEmbedMode\(\) \? 60 : 56;/);
});

test('正文不得自带纵向滚动条：滚动必须落在文档上（目录 sticky 自滚兜底豁免）', () => {
  // 正文容器（padding '0 32px 24px' 块）不得带 overflowY
  assert.doesNotMatch(readHelpPage(), /padding: '0 32px 24px',[^}]*overflowY/);
});

test('桌面 flex 行必须走文档流：不锁高度、正文顶带 0 底呼吸 24 保留', () => {
  const text = readHelpPage();
  assert.match(text, /<div style=\{\{ display: 'flex' \}\}>/);
  assert.match(text, /padding: '0 32px 24px'/);
});

test('包裹卡贴缘负外边距不得回潮（文档滚动条天然贴视口右缘，内容区留白与他页一致）', () => {
  assert.doesNotMatch(
    readHelpPage(),
    /marginInlineEnd: -dshLayoutToken/,
  );
});
