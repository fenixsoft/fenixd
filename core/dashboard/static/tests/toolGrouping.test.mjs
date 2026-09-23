// groupConsecutiveTools 同类连续聚合 + 工具卡片纯函数（add-run-record-readability 2.4）。
// 零依赖，node 原生 type-stripping 直载 .ts 源——需 Node ≥22.18（22.6–22.17 须
// 显式 --experimental-strip-types，20.x 不支持；下限同记于 package.json
// engines.node 与 release.yml CI 测试步骤，code-review item d2264576cec6）。
// 运行：cd core/dashboard/static && node --test tests/toolGrouping.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  TOOL_GROUP_THRESHOLD,
  describeToolInput,
  editFilePaths,
  formatElapsedSeconds,
  groupConsecutiveTools,
  isToolGroupItem,
  toolCardPreview,
  toolClassOf,
  toolGroupTitle,
} from '../src/components/claude-msg/toolGrouping.ts';

// 每用例独立工厂（code-review item 899393aaf80c）：模块级共享 seq 会让
// toolId（call_1…call_N）依赖用例执行顺序——重排用例、--test-name-pattern
// 过滤或拆分文件后，ID 相关失败难以定位。改为工厂闭包内计数，各用例自建
// toolMsg，跨用例零共享状态。
function makeToolMsgFactory() {
  let seq = 0;
  return (toolName, input) => {
    seq += 1;
    return {
      type: 'tool',
      isToolUse: true,
      toolName,
      toolInput: input,
      toolId: `call_${seq}`,
      timestamp: `2026-09-22T10:00:${String(seq % 60).padStart(2, '0')}`,
    };
  };
}

function thinkingMsg(text = '先看派发逻辑') {
  return { type: 'assistant', isThinking: true, content: text, timestamp: '2026-09-22T10:01:00' };
}

function groupTitles(items) {
  return items.filter(isToolGroupItem).map((g) => g.groupTitle || g.toolName);
}

// ── 同类连续聚合 ─────────────────────────────────────────────────────

test('查阅类：Read/Grep/Glob 混合同类连续成组，标题带计数', () => {
  const toolMsg = makeToolMsgFactory();
  const items = groupConsecutiveTools([
    toolMsg('Read', { file_path: '/a.py' }),
    toolMsg('Grep', { pattern: 'foo' }),
    toolMsg('Glob', { pattern: '*.py' }),
  ]);
  assert.equal(items.length, 1);
  assert.equal(items[0].groupKind, 'read');
  assert.equal(items[0].groupTitle, '查阅 3 个文件/模式');
});

test('命令类：连续 Bash 聚合为「执行 N 条命令」', () => {
  const toolMsg = makeToolMsgFactory();
  const items = groupConsecutiveTools([
    toolMsg('Bash', { command: 'ls' }),
    toolMsg('Bash', { command: 'pwd' }),
    toolMsg('Bash', { command: 'env' }),
  ]);
  assert.deepEqual(groupTitles(items), ['执行 3 条命令']);
});

test('编辑类：连续 Edit/Write 混合成组为「编辑 N 个文件」', () => {
  const toolMsg = makeToolMsgFactory();
  const items = groupConsecutiveTools([
    toolMsg('Edit', { file_path: '/a.py', old_string: 'x', new_string: 'y' }),
    toolMsg('Write', { file_path: '/b.py', content: 'x' }),
  ]);
  assert.equal(items.length, 1);
  assert.equal(items[0].groupKind, 'edit');
  assert.equal(items[0].groupTitle, '编辑 2 个文件');
});

test('间隔 thinking（开关关闭）不断组：Bash×2 + thinking + Bash×3 → 单组 5 条', () => {
  const toolMsg = makeToolMsgFactory();
  const items = groupConsecutiveTools(
    [
      toolMsg('Bash', { command: 'a' }),
      toolMsg('Bash', { command: 'b' }),
      thinkingMsg(),
      toolMsg('Bash', { command: 'c' }),
      toolMsg('Bash', { command: 'd' }),
      toolMsg('Bash', { command: 'e' }),
    ],
    false,
  );
  assert.equal(items.length, 1);
  assert.equal(items[0].messages.length, 5);
  assert.equal(items[0].groupTitle, '执行 5 条命令');
});

test('开关打开时 thinking 打断分组：Bash×2 + thinking + Bash×3 → 2 组 + thinking', () => {
  const toolMsg = makeToolMsgFactory();
  const items = groupConsecutiveTools(
    [
      toolMsg('Bash', { command: 'a' }),
      toolMsg('Bash', { command: 'b' }),
      thinkingMsg(),
      toolMsg('Bash', { command: 'c' }),
      toolMsg('Bash', { command: 'd' }),
      toolMsg('Bash', { command: 'e' }),
    ],
    true,
  );
  const titles = groupTitles(items);
  assert.deepEqual(titles, ['执行 2 条命令', '执行 3 条命令']);
  assert.ok(items.some((i) => !isToolGroupItem(i) && i.isThinking));
});

test('异类断组：Bash×2 + Edit → 「执行 2 条命令」+ 独立 Edit 卡片', () => {
  const toolMsg = makeToolMsgFactory();
  const items = groupConsecutiveTools([
    toolMsg('Bash', { command: 'a' }),
    toolMsg('Bash', { command: 'b' }),
    toolMsg('Edit', { file_path: '/a.py' }),
  ]);
  assert.equal(items.length, 2);
  assert.equal(items[0].groupTitle, '执行 2 条命令');
  assert.equal(isToolGroupItem(items[1]), false);
  assert.equal(items[1].toolName, 'Edit');
});

test('类外工具沿用同名连续：连续 Task 聚合但无语义化标题（badge 形态）', () => {
  const toolMsg = makeToolMsgFactory();
  const items = groupConsecutiveTools([
    toolMsg('Task', { prompt: 'a' }),
    toolMsg('Task', { prompt: 'b' }),
  ]);
  assert.equal(items.length, 1);
  assert.equal(isToolGroupItem(items[0]), true);
  assert.equal(items[0].groupKind, undefined);
  assert.equal(items[0].groupTitle, undefined);
  assert.equal(items[0].toolName, 'Task');
});

// ── 阈值 ─────────────────────────────────────────────────────────────

test('阈值 2：单条工具不聚合、逐条展示', () => {
  const toolMsg = makeToolMsgFactory();
  assert.equal(TOOL_GROUP_THRESHOLD, 2);
  const items = groupConsecutiveTools([toolMsg('Bash', { command: 'a' })]);
  assert.equal(items.length, 1);
  assert.equal(isToolGroupItem(items[0]), false);
});

// ── 编辑组路径去重 ───────────────────────────────────────────────────

test('editFilePaths：5 次调用 3 个路径按首现顺序去重', () => {
  const toolMsg = makeToolMsgFactory();
  const paths = editFilePaths([
    toolMsg('Edit', { file_path: '/a.py' }),
    toolMsg('Write', { file_path: '/b.py', content: 'x' }),
    toolMsg('Edit', { file_path: '/c.py' }),
    toolMsg('Edit', { file_path: '/a.py' }),
    toolMsg('Write', { file_path: '/b.py', content: 'y' }),
  ]);
  assert.deepEqual(paths, ['/a.py', '/b.py', '/c.py']);
});

test('editFilePaths：path 字段回退与非对象输入容错', () => {
  const toolMsg = makeToolMsgFactory();
  const paths = editFilePaths([
    toolMsg('Edit', { path: '/rel.py' }),
    toolMsg('Edit', ''),
    toolMsg('Edit', null),
  ]);
  assert.deepEqual(paths, ['/rel.py']);
});

// ── 卡片语义摘要（description 优先） ─────────────────────────────────

test('describeToolInput：有 description 时优先语义摘要', () => {
  const text = describeToolInput({
    command: 'python3 bin/run_full_suite.py --baseline x',
    description: '跑全量回归对齐基线',
  });
  assert.equal(text, '跑全量回归对齐基线');
});

test('describeToolInput：无 description 时回落 command 原文', () => {
  assert.equal(describeToolInput({ command: 'git status' }), 'git status');
});

test('describeToolInput：文件类工具回落 file_path，其余沿用既有兜底', () => {
  assert.equal(describeToolInput({ file_path: '/x/y.py' }), '/x/y.py');
  assert.equal(describeToolInput({ pattern: 'foo**' }), 'foo**');
  // 字符串形态 toolInput（JSON）也可解析
  assert.equal(describeToolInput(JSON.stringify({ command: 'ls', description: '列目录' })), '列目录');
});

// ── 耗时标注格式（有/无两分支） ──────────────────────────────────────

test('formatElapsedSeconds：510s → 8m30s，45s → 45s', () => {
  assert.equal(formatElapsedSeconds(510), '8m30s');
  assert.equal(formatElapsedSeconds(45), '45s');
  assert.equal(formatElapsedSeconds(60), '1m0s');
});

test('formatElapsedSeconds：无值/非法值返回空串（卡片不渲染）', () => {
  assert.equal(formatElapsedSeconds(Number.NaN), '');
  assert.equal(formatElapsedSeconds(-3), '');
});

// ── 工具类映射 ───────────────────────────────────────────────────────

test('toolClassOf / toolGroupTitle 映射表', () => {
  assert.equal(toolClassOf('Read'), 'read');
  assert.equal(toolClassOf('Grep'), 'read');
  assert.equal(toolClassOf('Glob'), 'read');
  assert.equal(toolClassOf('Bash'), 'bash');
  assert.equal(toolClassOf('Edit'), 'edit');
  assert.equal(toolClassOf('Write'), 'edit');
  assert.equal(toolClassOf('Task'), null);
  assert.equal(toolGroupTitle('read', 3), '查阅 3 个文件/模式');
  assert.equal(toolGroupTitle('bash', 5), '执行 5 条命令');
  assert.equal(toolGroupTitle('edit', 2), '编辑 2 个文件');
});

// ── toolCardPreview：task_started 回填字段优先（BUG-01 回归锚定） ────

test('toolCardPreview 优先回填的 taskDescription', () => {
  const toolMsg = makeToolMsgFactory();
  const msg = { ...toolMsg('Task', { prompt: '跑全量测试并汇报' }), taskDescription: 'Run dispatch tests' };
  assert.equal(toolCardPreview(msg), 'Run dispatch tests');
});

test('toolCardPreview 无回填时回落工具输入摘要（description 优先既有语义不变）', () => {
  const toolMsg = makeToolMsgFactory();
  assert.equal(toolCardPreview(toolMsg('Bash', { command: 'npm test' })), 'npm test');
  assert.equal(toolCardPreview(toolMsg('Read', { file_path: '/a/b.py', description: '看配置' })), '看配置');
});

test('toolCardPreview 回填为空白串时回落输入摘要', () => {
  const toolMsg = makeToolMsgFactory();
  const msg = { ...toolMsg('Task', { description: '输入里的描述' }), taskDescription: '   ' };
  assert.equal(toolCardPreview(msg), '输入里的描述');
});

// ── rendersNothing：兜底强制渲染的 thinking 照常断组（BUG-02 回归锚定） ──

test('兜底强制渲染的 thinking（thinkingForced）真实可见，打断同类连续分组', () => {
  const toolMsg = makeToolMsgFactory();
  const a = toolMsg('Bash', { command: 'echo a' });
  const t = { type: 'assistant', isThinking: true, content: '思考', timestamp: '2026-09-22T10:05:00', thinkingForced: true };
  const b = toolMsg('Bash', { command: 'echo b' });
  const items = groupConsecutiveTools([a, t, b], false);
  assert.equal(items.length, 3, '强制渲染的 thinking 可见，须断组');
  assert.ok(!items.some(isToolGroupItem), '断组后阈值不足不聚合');
});
