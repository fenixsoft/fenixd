// SPEC 名称列右键复制菜单测试（add-spec-name-copy-menu 任务 2.1）。
// 零依赖 node:test（同 specInfoIcon.test.mjs 习语：源码扫描钉 JSX 接线；
// 渲染行为由 npm run build 与浏览器场景覆盖）。
//
// 覆盖（行为契约 = specs/dashboard-spec-table 增量）：
// - 名称列单元格接线 antd Dropdown contextMenu trigger（右键拦截原生菜单）；
// - 菜单单项 key 'copy-name'、文案「复制 SPEC 名称」（单菜单项，无扩展项）；
// - copyToClipboard 单源复用：从 components/claude-msg/Markdown 导入，
//   list.tsx 内 MUST NOT 出现自写 execCommand / createElement('textarea')
//   剪贴板代码（非 secure context 降级由单源助手承担）；
// - 复制键为该行自身 record.name（英文名，不含中文标题/项目名）；
// - 移动端卡片流分支（非 dense）零接线：dense 早退先于 Dropdown。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const STATIC_ROOT = join(import.meta.dirname, '..');
const readSrc = (rel) => readFileSync(join(STATIC_ROOT, rel), 'utf-8');

const listSrc = readSrc('src/pages/projects/list.tsx');

// ── SpecNameCell 共用单源块（桌面表格名称列 + 移动卡片缺省形态） ──────

const fnStart = listSrc.indexOf('function SpecNameCell(');
const specNameCellBlock = () => {
  assert.ok(fnStart > 0, 'SpecNameCell 组件应存在（名称列共用单源）');
  // 组件闭括号以 `\n}\n` 锚定（`\n}` 会误匹配 props 类型注解收尾 `}: {`）
  return listSrc.slice(fnStart, listSrc.indexOf('\n}\n', fnStart) + 3);
};

test('名称列接线：contextMenu trigger（右键拦截原生菜单弹自绘菜单）', () => {
  const block = specNameCellBlock();
  assert.ok(block.includes('<Dropdown'), '名称列单元格应外包 antd Dropdown');
  assert.ok(block.includes("trigger={['contextMenu']}"), 'trigger 应为 contextMenu（右键触发）');
  // 接线单点：全文件 contextMenu 仅名称列一处，其他列/表头/空白处不接线
  const hits = listSrc.split("trigger={['contextMenu']}").length - 1;
  assert.equal(hits, 1, 'contextMenu trigger 应仅名称列一处（其他区域保持浏览器原生默认）');
});

test('菜单单项：key copy-name、文案经 intl id projects.list.menu.copyName（zh 目录=「复制 SPEC 名称」），无扩展菜单项', () => {
  const block = specNameCellBlock();
  assert.ok(block.includes("key: 'copy-name'"), '菜单项 key 应为 copy-name');
  assert.ok(block.includes("label: t('projects.list.menu.copyName')"), '菜单项文案应钉 intl id projects.list.menu.copyName');
  // 范围界定：不做「复制路径」「复制项目名」等多菜单项扩展
  assert.ok(!block.includes('复制路径'), '不应出现「复制路径」扩展项');
  assert.ok(!block.includes('复制项目名'), '不应出现「复制项目名」扩展项');
});

test('copyToClipboard 单源复用：单源导入，list.tsx 无自写剪贴板实现', () => {
  assert.ok(
    listSrc.includes("import { copyToClipboard } from '@/components/claude-msg/Markdown';"),
    '应从 components/claude-msg/Markdown 导入既有单源助手',
  );
  const block = specNameCellBlock();
  assert.ok(block.includes('copyToClipboard(record.name)'), '复制调用应命中单源助手');
  // 剪贴板实现细节 MUST NOT 在本文件重写（textarea/execCommand 降级属单源助手）
  assert.ok(!listSrc.includes('execCommand'), 'list.tsx 不应出现自写 execCommand 剪贴板代码');
  assert.ok(
    !listSrc.includes("createElement('textarea'") && !listSrc.includes('createElement("textarea"'),
    'list.tsx 不应出现自写 createElement("textarea") 剪贴板代码',
  );
});

test('复制键为该行自身 record.name（英文名，不含中文标题/项目名）', () => {
  const block = specNameCellBlock();
  assert.ok(block.includes('copyToClipboard(record.name)'), '复制内容应为 record.name（kebab-case id）');
  // 成功/失败如实提示，失败不误报成功
  assert.ok(block.includes("message.success(t('projects.list.copiedName'))"), '成功应非阻塞提示（intl id projects.list.copiedName，zh 目录=「已复制 SPEC 名称」）');
  assert.ok(block.includes('message.error('), '失败应有失败提示（含原因，不误报成功）');
});

test('菜单项点击阻断行导航：domEvent.stopPropagation（React portal 冒泡进行级 onClick）', () => {
  const block = specNameCellBlock();
  assert.ok(
    block.includes('domEvent.stopPropagation()'),
    '菜单 onClick 须阻断 domEvent——弹层经 React portal 渲染，事件沿组件树冒泡会命中行 onRow onClick 触发导航',
  );
});

test('移动端卡片流分支零接线：dense 早退先于 Dropdown（触屏无右键语义）', () => {
  const block = specNameCellBlock();
  const guard = block.indexOf('if (!dense)');
  const dropdown = block.indexOf('<Dropdown');
  assert.ok(guard > 0, '应存在非 dense（移动卡片流）早退分支');
  assert.ok(dropdown > guard, 'contextMenu Dropdown 应只接在 dense（桌面表格）分支之后，移动分支零改动');
});
