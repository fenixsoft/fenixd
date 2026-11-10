// SPEC 列表信息图标测试（add-spec-info-icon-tooltip 任务 3.1）。
// 零依赖 node:test（同 specRowClick.test.mjs 习语：源码扫描钉 JSX 接线；
// 渲染行为由 npm run build 与浏览器场景覆盖）。
//
// 覆盖（行为契约 = specs/dashboard-spec-table 增量）：
// - expandedRowRender / rowExpandable 不复现于列表表格（信息子行退役）；
// - spec-card-info-row amber 信息行移除（移动端退役）；
// - SpecInfoIcon 共用单源：Popover trigger 含 hover 与 click（D1 双触发）、
//   InfoCircleOutlined 接线（D2 形态）、完整文本 pre-wrap 不截断（D3）、
//   清除按钮 stopPropagation + onClearError 复用、图标触发器自身
//   stopPropagation（D6 防行导航）；
// - 桌面状态列 / 移动卡胶囊行两处接线均以 `record.error` 条件渲染
//   （空/null 不渲染、无占位元素），移动端 32px 触控目标（D5）；
// - 清除端点 /api/spec-error-clear 契约字符串不变（后端零改动面）。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const STATIC_ROOT = join(import.meta.dirname, '..');
const readSrc = (rel) => readFileSync(join(STATIC_ROOT, rel), 'utf-8');

const listSrc = readSrc('src/pages/projects/list.tsx');
const dashSrc = readSrc('src/services/dashboard.ts');

// ── SpecInfoIcon 共用单源块 ──────────────────────────────────────────

const fnStart = listSrc.indexOf('function SpecInfoIcon(');
const specInfoIconBlock = () => {
  assert.ok(fnStart > 0, 'SpecInfoIcon 组件应存在（桌面/移动共用单源）');
  // 组件闭括号以 `\n}\n` 锚定（`\n}` 会误匹配 props 类型注解收尾 `}: {`）
  return listSrc.slice(fnStart, listSrc.indexOf('\n}\n', fnStart) + 3);
};

test('信息子行退役：expandedRowRender / rowExpandable 不复现于列表表格', () => {
  assert.ok(!listSrc.includes('expandedRowRender'), '桌面行下信息子行应已退役');
  assert.ok(!listSrc.includes('rowExpandable'), 'rowExpandable 门控应随子行一并移除');
  // 受控展开配置收缩后仍受控驱动树形子级（antd v5 凭 keys 即可）
  const e0 = listSrc.indexOf('expandable={{');
  const expandable = listSrc.slice(e0, listSrc.indexOf('}}', e0) + 2);
  assert.ok(expandable.includes('expandedRowKeys: expandedKeys'), '受控 expandedRowKeys 应保留');
  assert.ok(expandable.includes('onExpandedRowsChange: onExpandedKeysChange'), '受控 onExpandedRowsChange 应保留');
  assert.ok(expandable.includes('columnWidth: 28'), '展开列宽应保留');
});

test('移动端 amber 信息行退役：spec-card-info-row 不复现', () => {
  assert.ok(!listSrc.includes('spec-card-info-row'), 'amber 软底信息行应已移除');
});

test('Popover 触发：hover 与 click 双触发（D1 桌面悬浮 / 触屏点按兜底）', () => {
  const block = specInfoIconBlock();
  assert.ok(block.includes('<Popover'), '弹层应用 Popover（弹层内含清除交互，Tooltip 不承载交互）');
  assert.ok(block.includes("trigger={['hover', 'click']}"), 'trigger 应含 hover 与 click');
});

test('InfoCircleOutlined 接线：14px + token.colorWarning（D2 形态与语义色）', () => {
  assert.ok(
    listSrc.includes("import { ClockCircleOutlined, InfoCircleOutlined } from '@ant-design/icons';"),
    '应导入 InfoCircleOutlined',
  );
  const block = specInfoIconBlock();
  assert.ok(block.includes('<InfoCircleOutlined'), '图标应接线 InfoCircleOutlined');
  assert.ok(block.includes('fontSize: 14'), '图标视觉应约 14px');
  assert.ok(block.includes('color: token.colorWarning'), '图标色应取 token.colorWarning（warning 橙语义）');
});

test('弹层内容：完整文本 pre-wrap 可换行不截断 + maxWidth 限宽（D3）', () => {
  const block = specInfoIconBlock();
  assert.ok(block.includes("whiteSpace: 'pre-wrap'"), '弹层文本应 pre-wrap 按原样换行');
  assert.ok(block.includes('maxWidth:'), '弹层应 maxWidth 限宽防超宽');
  assert.ok(block.includes('{record.error}'), '弹层应渲染完整 error 文本');
});

test('清除按钮：stopPropagation + 复用既有 onClearError（契约零改动）', () => {
  const block = specInfoIconBlock();
  assert.ok(block.includes('e.stopPropagation()'), '清除按钮应 stopPropagation 防触发行/卡导航');
  assert.ok(block.includes('onClearError(record)'), '清除应复用既有 onClearError handler');
  assert.ok(block.includes('size="small"'), '清除按钮应为 small 形态');
  assert.ok(block.includes('清除'), '按钮文案应为「清除」');
});

test('图标触发器自身 stopPropagation（D6：点图标不触发行导航）', () => {
  const block = specInfoIconBlock();
  assert.ok(
    block.includes('onClick={(e) => e.stopPropagation()}'),
    '图标触发器 click 应短路行级导航',
  );
  assert.ok(block.includes('data-testid="spec-info-icon"'), '图标应有测试锚点');
});

// ── 桌面 / 移动两处接线 ──────────────────────────────────────────────

test('桌面状态列接线：error 非空才渲染、紧随 StatusWaitGroup 之后', () => {
  const c0 = listSrc.indexOf("title: '状态'");
  const col = listSrc.slice(c0, listSrc.indexOf('title:', c0 + 10));
  assert.ok(col.includes('<SpecInfoIcon record={record} onClearError={onClearError} />'), '状态列应接线 SpecInfoIcon');
  assert.ok(col.includes('record.error ?'), '应以 record.error 条件渲染（空/null 不渲染、无占位）');
  const pillAt = col.indexOf('<Pill tone={m.tone}>');
  const waitAt = col.indexOf('<StatusWaitGroup record={record} />');
  const iconAt = col.indexOf('<SpecInfoIcon');
  assert.ok(pillAt > 0 && waitAt > pillAt && iconAt > waitAt, '图标应紧随状态胶囊与等待组之后');
});

test('移动卡胶囊行接线：32px 触控目标（D5）、状态 Pill 旁', () => {
  const p0 = listSrc.indexOf('className="spec-card-pills"');
  const pills = listSrc.slice(p0, listSrc.indexOf('spec-card-progress', p0));
  assert.ok(
    pills.includes('<SpecInfoIcon record={record} onClearError={onClearError} tapSize={32} />'),
    '移动卡应以 tapSize=32 接线（外层点按目标 ≥32px，同 ⋮ 触控纪律）',
  );
  assert.ok(pills.includes('record.error ?'), '移动卡也应以 record.error 条件渲染');
});

// ── 清除端点契约（后端零改动面钉死） ─────────────────────────────────

test('清除端点契约不变：POST /api/spec-error-clear?project=&spec=', () => {
  assert.ok(
    dashSrc.includes('`/api/spec-error-clear?project=${encodeURIComponent(project)}&spec=${encodeURIComponent(spec)}`'),
    'clearSpecError 端点字符串应保持不变',
  );
});
