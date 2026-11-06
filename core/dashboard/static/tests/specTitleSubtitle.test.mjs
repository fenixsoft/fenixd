// SPEC 中文标题副标题测试（add-spec-chinese-title 任务 2.4）。
// 零依赖 node:test（同 qualityGates.test.mjs 习语：纯逻辑直测 + 源码扫描钉
// JSX 接线；渲染行为由 npm run build 与浏览器冒烟覆盖）。
//
// 覆盖：
// - specKeywordHit 匹配语义（英文名 OR 中文标题、大小写不敏感、无标题退化、
//   空关键词恒过）；
// - 两处名称列副标题接线（v1 list.tsx / v2 projectDetail.tsx）：有 title 渲染
//   守卫、无 title 不渲染（falsy 三元）、次级视觉（字号/色/单行省略）、副标题
//   在 Why 悬浮 Popover 之外不承载交互、树形缩进对齐（副标题与主行同单元格
//   同包裹层，桌面表格与移动卡片共用 SpecNameCell）；
// - SpecSummary 类型透传字段与 v2 名称既有交互保持；
// - 详情标题栏中文标题下方行（add-spec-subtitle-and-row-click 任务 1.1/1.3
//   原 subtitle 槽形态经 2026-11-06 用户指令「中文标题放在英文标题下方」改版
//   收进 richTitle 内部）：两详情页零 subtitle 槽、块级第二行次级视觉（字号/
//   色/单行省略）、移动端页级 gate、v2 组合形态四分支单源 combineSpecSubtitle、
//   SpecDetail 类型透传。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { combineSpecSubtitle, specKeywordHit } from '../src/pages/projects/specTitle.ts';

const STATIC_ROOT = join(import.meta.dirname, '..');
const readSrc = (rel) => readFileSync(join(STATIC_ROOT, rel), 'utf-8');

// ── specKeywordHit：id/name 关系下标题参与匹配的唯一例外 ──────────────

test('英文名命中保留（既有行为不变）', () => {
  assert.equal(specKeywordHit('add-knowledge-inbox-pipeline', '知识收件箱回填管线', 'inbox'), true);
  assert.equal(specKeywordHit('add-foo', null, 'foo'), true);
});

test('中文标题命中保留（英文名不含关键词）', () => {
  assert.equal(specKeywordHit('add-knowledge-inbox-pipeline', '知识收件箱回填管线', '收件箱'), true);
  assert.equal(specKeywordHit('add-foo', '知识收件箱回填管线', '回填'), true);
});

test('大小写不敏感：标题含拉丁字符时同样折小写匹配', () => {
  assert.equal(specKeywordHit('add-foo', 'Dashboard 优化体验', 'dashboard'), true);
  assert.equal(specKeywordHit('add-foo', 'Dashboard 优化体验', 'DASHBOARD'), true);
});

test('双不命中剔除；无标题退化仅英文名参与', () => {
  assert.equal(specKeywordHit('add-foo', '知识收件箱回填管线', 'zzz'), false);
  assert.equal(specKeywordHit('add-foo', null, '收件箱'), false);
  assert.equal(specKeywordHit('add-foo', undefined, '收件箱'), false);
  assert.equal(specKeywordHit('add-foo', '', '收件箱'), false);
});

test('空关键词不过滤（恒保留）', () => {
  assert.equal(specKeywordHit('add-foo', null, ''), true);
  assert.equal(specKeywordHit('add-foo', '标题', ''), true);
});

// ── v1 list.tsx：名称列副标题接线 ────────────────────────────────────

const listSrc = readSrc('src/pages/projects/list.tsx');

test('v1 SpecNameCell：有 title 渲染副标题（次级视觉单行省略）', () => {
  assert.ok(listSrc.includes('{record.title ? ('), 'SpecNameCell 应以 record.title 三元守卫副标题渲染');
  assert.ok(listSrc.includes('className="spec-title-sub"'), '副标题应有稳定类名锚');
  // 次级视觉：12px（主行 16px）+ tertiary 文字色 + 单行省略三件套
  const block = listSrc.slice(listSrc.indexOf('spec-title-sub') - 200, listSrc.indexOf('spec-title-sub') + 500);
  assert.ok(block.includes('fontSize: 12'), '副标题字号应小于主行（12px < 16px）');
  assert.ok(block.includes('token.colorTextTertiary'), '副标题应为 tertiary 文字色');
  assert.ok(block.includes("textOverflow: 'ellipsis'"), '副标题应单行省略');
  assert.ok(block.includes("whiteSpace: 'nowrap'"), '副标题应不换行');
});

test('v1 副标题在 Why 悬浮 Popover 之外（不承载点击/悬停交互）', () => {
  // 先切出 SpecNameCell 区域再定位（文件后部还有验证列 Popover，不可全文件搜索）
  const cellStart = listSrc.indexOf('function SpecNameCell(');
  const cellEnd = listSrc.indexOf('// ── 验证列悬浮提示');
  const cell = listSrc.slice(cellStart, cellEnd);
  const popoverEnd = cell.indexOf('</Popover>');
  const subStart = cell.indexOf('{record.title ? (');
  assert.ok(popoverEnd > 0 && subStart > popoverEnd, '副标题渲染应位于 </Popover> 之后（Why 悬浮仅挂主行 span）');
});

test('v1 树形缩进对齐：副标题与主行同包裹层，桌面表格与移动卡片共用 SpecNameCell', () => {
  const cellStart = listSrc.indexOf('function SpecNameCell(');
  const cellEnd = listSrc.indexOf('// ── 验证列悬浮提示');
  const cell = listSrc.slice(cellStart, cellEnd);
  assert.ok(cell.includes('{ minWidth: 0 }'), '主行+副标题应共用 minWidth:0 包裹层（缩进随单元格）');
  assert.ok(cell.includes('<div style={{ minWidth: 0 }}>'), '包裹层应在 SpecNameCell 内');
  // 桌面列渲染与移动卡片两处消费同一单元格 → 副标题自动随两处缩进
  const uses = [...listSrc.matchAll(/<SpecNameCell project=\{project\} record=\{record\}( dense)? \/>/g)].length;
  assert.ok(uses >= 2, `桌面表格与移动卡片应共用 SpecNameCell（实际 ${uses} 处）`);
});

test('v1 名称关键字过滤经 specKeywordHit 单源（标题命中）', () => {
  assert.ok(listSrc.includes("import { specKeywordHit } from './specTitle';"), '应从 specTitle 单源导入');
  assert.ok(listSrc.includes('specKeywordHit(s.name, s.title, kw)'), '过滤应命中英文名 OR 中文标题');
  assert.ok(!listSrc.includes('!s.name.toLowerCase().includes(kw)'), '裸英文名包含匹配应已被单源替换');
});

// ── v2 projectDetail.tsx：SPEC 表格名称列副标题接线 ──────────────────

const v2Src = readSrc('src/pages/v2/projectDetail.tsx');

test('v2 名称列：有 title 渲染副标题（V2 次级文字 token、小字号、单行省略）', () => {
  assert.ok(v2Src.includes('{s.title ? ('), 'v2 名称单元格应以 s.title 三元守卫副标题渲染');
  const block = v2Src.slice(v2Src.indexOf('{s.title ? (') - 100, v2Src.indexOf('{s.title ? (') + 400);
  assert.ok(block.includes('className="v2-ellipsis"'), '副标题应复用 v2-ellipsis 单行省略');
  assert.ok(block.includes('V2_TEXT_TERTIARY'), '副标题应用 v2 台账次级文字 token');
  assert.ok(block.includes('fontSize: 12'), '副标题字号应小于主行（12px < 13.5px）');
});

test('v2 名称交互不变：主行 span 点击跳详情与 title 属性保持，副标题无独立点击目标', () => {
  const cell = v2Src.slice(v2Src.indexOf("title: '名称'"), v2Src.indexOf("title: '优先级'"));
  assert.ok(cell.includes('onClick={(e) => {'), '主行点击跳转应保留');
  assert.ok(cell.includes('title={s.name}'), '英文名溢出提示 title 属性应保留');
  const subBlock = v2Src.slice(v2Src.indexOf('{s.title ? ('), v2Src.indexOf('{s.title ? (') + 400);
  assert.ok(!subBlock.includes('onClick'), '副标题文本不承载独立点击目标');
});

// ── SpecSummary 类型透传 ─────────────────────────────────────────────

test('SpecSummary 增加 title 可空类型（数据源注释标注 id/name 关系）', () => {
  const svc = readSrc('src/services/dashboard.ts');
  assert.ok(svc.includes('title?: string | null;'), 'SpecSummary 应含 title?: string | null');
  assert.ok(svc.includes('add-spec-chinese-title'), '类型注释应标注能力来源与 id/name 关系');
});

// ── v1 detail.tsx：详情标题栏中文标题下方行（2026-11-06 用户指令「中文标题
// 放在英文标题下方」改版；原 add-spec-subtitle-and-row-click 1.2 subtitle 槽
// 形态退役——下方行收进 richTitle 富节点内部，不经 subtitle 槽）──

const detailSrc = readSrc('src/pages/projects/detail.tsx');

test('v1 详情四处 PageTitleBar 声明零 subtitle 槽（中文标题已收进富标题下方行）', () => {
  const decls = [...detailSrc.matchAll(/<PageTitleBar[\s\S]*?\/>/g)].map((m) => m[0]);
  assert.equal(decls.length, 4, 'detail.tsx 应恰有四处 PageTitleBar 声明（参数缺失/loading/error/主内容）');
  assert.equal(detailSrc.includes('subtitle='), false, '不应再经 subtitle 槽声明中文标题（槽位行尾跟随非详情形态）');
});

test('v1 详情中文标题下方行：richTitle 内块级第二行（次级视觉单行省略 + 移动端 gate + 缺失容错）', () => {
  const at = detailSrc.indexOf('{!isMobile && detail?.title ? (');
  assert.ok(at > 0, '中文标题下方行应以 !isMobile + detail?.title 双条件守卫渲染');
  const block = detailSrc.slice(at, detailSrc.indexOf(') : null}', at) + 8);
  assert.ok(block.includes("display: 'block'"), '下方行应为块级第二行');
  assert.ok(block.includes('fontSize: 12'), '下方行字号应次级（12px）');
  assert.ok(block.includes('token.colorTextTertiary'), '下方行应为 tertiary 文字色');
  assert.ok(block.includes("textOverflow: 'ellipsis'"), '下方行应单行省略');
  assert.ok(block.includes("whiteSpace: 'nowrap'"), '下方行应不换行');
  assert.ok(block.includes('{detail.title}'), '下方行数据源应为详情响应 title');
});

// ── v2 specDetail.tsx：中文标题下方行组合（原 add-spec-subtitle-and-row-click
// 1.3 subtitle 槽形态退役，组合单源与缺失容错语义保持）──

const v2DetailSrc = readSrc('src/pages/v2/specDetail.tsx');

test('v2 详情中文标题组合单源 combineSpecSubtitle（组合语义不下放页面自拼）', () => {
  assert.ok(
    v2DetailSrc.includes('const chineseTitle = combineSpecSubtitle(detail?.title, detail?.branch);'),
    'v2 下方行应经单源组合函数取值（title+branch 四分支语义保持）',
  );
  assert.ok(v2DetailSrc.includes("from '@/pages/projects/specTitle'"), '组合函数应从 specTitle 单源导入');
});

test('v2 详情中文标题下方行：richTitle 内块级第二行（移动端 gate + 次级视觉 + 零 subtitle 槽）', () => {
  assert.equal(v2DetailSrc.includes('subtitle='), false, '不应再经 subtitle 槽声明（槽位行尾跟随非详情形态）');
  const at = v2DetailSrc.indexOf('{!mobile && chineseTitle ? (');
  assert.ok(at > 0, '中文标题下方行应以 !mobile + chineseTitle 双条件守卫渲染');
  const block = v2DetailSrc.slice(at, v2DetailSrc.indexOf(') : null}', at) + 8);
  assert.ok(block.includes("display: 'block'"), '下方行应为块级第二行');
  assert.ok(block.includes('fontSize: 12'), '下方行字号应次级（12px）');
  assert.ok(block.includes('V2_TEXT_TERTIARY'), '下方行应用 v2 次级文字 token');
  assert.ok(block.includes("textOverflow: 'ellipsis'"), '下方行应单行省略');
});

test('combineSpecSubtitle 组合形态四分支（title+branch / 仅 branch / 仅 title / 双空）', () => {
  assert.equal(combineSpecSubtitle('中文标题', 'main'), '中文标题 · main', '双非空为中点组合');
  assert.equal(combineSpecSubtitle('中文标题', null), '中文标题', 'branch 空只显中文标题');
  assert.equal(combineSpecSubtitle(null, 'main'), 'main', 'title 空维持 branch 单独显示');
  assert.equal(combineSpecSubtitle(null, undefined), undefined, '双空不渲染');
  assert.equal(combineSpecSubtitle('', ''), undefined, '空串按缺失容错（与列表规则一致）');
});

// ── SpecDetail 类型透传 ─────────────────────────────────────────────

test('SpecDetail 增加 title 可空类型（注释标注 id/name 关系与详情 API 透传来源）', () => {
  const svc = readSrc('src/services/dashboard.ts');
  const start = svc.indexOf('export interface SpecDetail');
  const iface = svc.slice(start, svc.indexOf('\n}', start));
  assert.ok(iface.includes('title?: string | null;'), 'SpecDetail 应含 title?: string | null');
  assert.ok(iface.includes('add-spec-subtitle-and-row-click'), '字段注释应标注能力来源');
  assert.ok(iface.includes('/api/specs/<spec>'), '字段注释应标注详情 API 透传来源');
});
