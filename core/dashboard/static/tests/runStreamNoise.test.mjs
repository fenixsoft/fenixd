// runEventsToChatMessages 事件分类表逐行锚定（add-run-record-readability 1.5）。
// 零依赖，node 原生 type-stripping 直载 .ts 源——需 Node ≥22.18（23.6+ 同样
// 默认开启；22.6–22.17 须显式 --experimental-strip-types；20.x 无此能力会以
// ERR_UNKNOWN_FILE_EXTENSION 失败）。下限同记于 package.json engines.node，
// CI 测试步骤（release.yml test job，node 22）按此守护
//（code-review item d2264576cec6）。
// 运行：cd core/dashboard/static && node --test tests/runStreamNoise.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { runEventsToChatMessages } from '../src/components/claude-msg/runEvents.ts';
import { groupConsecutiveTools } from '../src/components/claude-msg/toolGrouping.ts';

// 事件构造辅助：SDK 结构化事件为 type:"system" + subtype 形态
const sys = (subtype, extra = {}) => ({ type: 'system', subtype, ...extra });

function allTexts(msgs) {
  return msgs.map((m) => String(m.content || ''));
}

// ── 静默名单：不产出任何可见行 ────────────────────────────────────────

const SILENT_KINDS = [
  'tool_progress',
  'background_tasks_changed',
  'commands_changed',
  'run_metrics',
  'init',
  'status',
  'task_updated',
  'hook_started',
  'hook_response',
  'superseded',
  'turn_extension',
  'timeout_extension',
];

test('静默名单：顶层 type 形态不产出行', () => {
  for (const kind of SILENT_KINDS) {
    const msgs = runEventsToChatMessages([{ type: kind }, { type: kind, line: 'x' }]);
    assert.equal(msgs.length, 0, `kind=${kind} 应静默`);
  }
});

test('静默名单：system+subtype 形态不产出行（kind 归一化前置）', () => {
  for (const kind of SILENT_KINDS) {
    const msgs = runEventsToChatMessages([sys(kind)]);
    assert.equal(msgs.length, 0, `kind=${kind} 应静默`);
  }
});

// 静默例外二（code-review item 3dda29b6297c）：名单内事件带非空 error 载荷
// 渲染原因条，不再整段吞掉（superseded 的门失败原因此前不可见）
test('静默例外：名单内事件带非空 error 载荷渲染原因条，零载荷仍静默', () => {
  const msgs = runEventsToChatMessages([
    { type: 'superseded', error: '[artifact-structural] exit 0 但交付物缺失' },
  ]);
  assert.equal(msgs.length, 1);
  assert.equal(msgs[0].type, 'system');
  assert.match(String(msgs[0].content), /系统事件（superseded）/);
  assert.match(String(msgs[0].content), /\[artifact-structural\]/);
  // 长 error 截断到 80 字
  const long = 'x'.repeat(200);
  const truncated = runEventsToChatMessages([{ type: 'superseded', error: long }]);
  assert.ok(String(truncated[0].content).length < 200);
  assert.ok(String(truncated[0].content).endsWith('…'));
  // 零载荷心跳照旧静默
  assert.equal(runEventsToChatMessages([{ type: 'superseded' }]).length, 0);
});

test('tool_progress 心跳穿插不打断连续同名工具分组', () => {
  const tool = (id) => ({
    type: 'assistant',
    message: { content: [{ type: 'tool_use', id, name: 'Bash', input: { command: `cmd ${id}` } }] },
  });
  const events = [
    tool('a'),
    { type: 'tool_progress' },
    tool('b'),
    sys('status'),
    tool('c'),
  ];
  const items = groupConsecutiveTools(runEventsToChatMessages(events));
  assert.equal(items.length, 1);
  assert.equal(items[0].toolName, 'Bash');
  assert.equal(items[0].messages.length, 3);
});

// ── fail-open：名单外结构化事件渲染占位条（归一化 kind） ─────────────

test('fail-open：顶层未知 kind 渲染「系统事件（<kind>）」占位条', () => {
  const msgs = runEventsToChatMessages([{ type: 'liveness_shortcut' }]);
  assert.equal(msgs.length, 1);
  assert.equal(msgs[0].type, 'system');
  assert.equal(msgs[0].content, '系统事件（liveness_shortcut）');
});

test('fail-open：system 形态未知 subtype 显示归一化 kind（非 system）', () => {
  const msgs = runEventsToChatMessages([sys('mystery_event')]);
  assert.equal(msgs.length, 1);
  assert.equal(msgs[0].content, '系统事件（mystery_event）');
  assert.doesNotMatch(msgs[0].content, /系统事件（system）/);
});

// ── stderr 错误词表两分支 ─────────────────────────────────────────────

test('stderr：含错误关键词渲染为系统行', () => {
  const msgs = runEventsToChatMessages([
    { type: 'stderr', line: 'Traceback (most recent call last):' },
    { type: 'stderr', line: 'ECONNREFUSED connecting to gateway' },
    { type: 'stderr', line: 'Error: boom' },
    { type: 'stderr', line: 'build FATAL failure' },
    { type: 'stderr', line: '2 tests failed' },
  ]);
  assert.equal(msgs.length, 5);
  const texts = allTexts(msgs).join('|');
  assert.match(texts, /Traceback/);
  assert.match(texts, /ECONNREFUSED/);
  assert.match(texts, /Error: boom/);
  assert.doesNotMatch(texts, /\[stderr\]/);
});

test('stderr：非错误行静默', () => {
  const msgs = runEventsToChatMessages([
    { type: 'stderr', line: '[claude-code:unrecognized_model] ...' },
    { type: 'stderr', line: 'streaming chunk 42' },
  ]);
  assert.equal(msgs.length, 0);
});

// ── 信息类事件语义化系统条 ───────────────────────────────────────────

test('provider_marker 渲染为模型路由条', () => {
  const msgs = runEventsToChatMessages([
    { type: 'provider_marker', provider: 'bigmodel.cn', model: 'glm-5.3-flash', chain_index: 0, chain_len: 4 },
  ]);
  assert.equal(msgs.length, 1);
  assert.equal(msgs[0].type, 'system');
  const text = msgs[0].content;
  assert.match(text, /bigmodel\.cn/);
  assert.match(text, /glm-5\.3-flash/);
  assert.match(text, /1\/4/);
  assert.doesNotMatch(text, /\[provider_marker\]/);
});

test('provider_marker 字段缺失降级为「模型路由」', () => {
  const msgs = runEventsToChatMessages([{ type: 'provider_marker' }]);
  assert.equal(msgs.length, 1);
  assert.equal(msgs[0].content, '模型路由');
});

test('transient_retry 渲染为瞬断告警条（原因+退避+序号+error 摘要）', () => {
  const msgs = runEventsToChatMessages([
    {
      type: 'transient_retry',
      reason: 'artifact_gate',
      backoff_seconds: 30,
      retry_number: 1,
      error: '[artifact-structural] exit 0 但交付物缺失',
    },
  ]);
  assert.equal(msgs.length, 1);
  const text = msgs[0].content;
  assert.match(text, /artifact_gate/);
  assert.match(text, /30s/);
  assert.match(text, /第 1 次重试/);
  assert.match(text, /artifact-structural/);
  assert.doesNotMatch(text, /\[transient_retry\]/);
});

test('transient_retry 载荷缺失降级且 error 摘要截断 80 字', () => {
  const degraded = runEventsToChatMessages([{ type: 'transient_retry' }]);
  assert.equal(degraded.length, 1);
  assert.equal(degraded[0].content, '网关瞬断');

  const long = 'x'.repeat(200);
  const truncated = runEventsToChatMessages([{ type: 'transient_retry', error: long }]);
  assert.equal(truncated.length, 1);
  assert.ok(truncated[0].content.length < 200);
  assert.match(truncated[0].content, /…$/);
});

test('compact_boundary 渲染为压缩条（compact_metadata 嵌套载荷）', () => {
  const msgs = runEventsToChatMessages([
    sys('compact_boundary', {
      compact_metadata: { trigger: 'auto', pre_tokens: 166773, post_tokens: 8154 },
    }),
  ]);
  assert.equal(msgs.length, 1);
  const text = msgs[0].content;
  assert.match(text, /166773/);
  assert.match(text, /8154/);
  assert.match(text, /auto/);
  assert.doesNotMatch(text, /\[compact_boundary\]/);
});

test('compact_boundary 载荷缺失降级为「上下文压缩」', () => {
  const msgs = runEventsToChatMessages([sys('compact_boundary')]);
  assert.equal(msgs.length, 1);
  assert.equal(msgs[0].content, '上下文压缩');
});

test('vcs_state_changed kind=commit 渲染提交条（分支名，无哈希字段不渲染哈希）', () => {
  const msgs = runEventsToChatMessages([
    sys('vcs_state_changed', { kind: 'commit', branch: 'fenix/add-run-record-readability-1790071892', cwd: '/x' }),
  ]);
  assert.equal(msgs.length, 1);
  const text = msgs[0].content;
  assert.match(text, /提交/);
  assert.match(text, /fenix\/add-run-record-readability-1790071892/);
  assert.doesNotMatch(text, /\[vcs_state_changed\]/);
});

test('vcs_state_changed 其他 kind 静默', () => {
  const msgs = runEventsToChatMessages([sys('vcs_state_changed', { kind: 'stage', branch: 'x' })]);
  assert.equal(msgs.length, 0);
});

// ── 任务生命周期回填 ─────────────────────────────────────────────────

function taskToolUse(id) {
  return {
    type: 'assistant',
    message: { content: [{ type: 'tool_use', id, name: 'Task', input: { prompt: 'run tests' } }] },
  };
}

test('task_started/notification 凭 tool_use_id 回填 Task 卡片，不渲染独立行', () => {
  const msgs = runEventsToChatMessages([
    taskToolUse('call_X'),
    sys('task_started', { task_id: 'T1', tool_use_id: 'call_X', description: 'Run dispatch tests' }),
    sys('task_notification', { task_id: 'T1', tool_use_id: 'call_X', status: 'completed', summary: '12 tests passed' }),
  ]);
  assert.equal(msgs.length, 1);
  const tool = msgs[0];
  assert.equal(tool.type, 'tool');
  assert.equal(tool.taskDescription, 'Run dispatch tests');
  assert.equal(tool.taskStatus, 'completed');
  assert.equal(tool.taskSummary, '12 tests passed');
});

test('task_notification 无匹配卡片时兜底为系统条（含 summary）', () => {
  const msgs = runEventsToChatMessages([
    sys('task_notification', { task_id: 'T9', tool_use_id: 'call_MISSING', status: 'completed', summary: '9 tests passed' }),
  ]);
  assert.equal(msgs.length, 1);
  assert.equal(msgs[0].type, 'system');
  assert.match(msgs[0].content, /9 tests passed/);
  assert.doesNotMatch(msgs[0].content, /\[task_notification\]/);
});

test('task_started 无匹配卡片时兜底为系统条（含 description）', () => {
  const msgs = runEventsToChatMessages([
    sys('task_started', { task_id: 'T9', tool_use_id: 'call_MISSING', description: 'dispatch work' }),
  ]);
  assert.equal(msgs.length, 1);
  assert.equal(msgs[0].type, 'system');
  assert.match(msgs[0].content, /dispatch work/);
});

// ── tool_progress 耗时映射 ───────────────────────────────────────────

test('tool_progress 按 parent_tool_use_id 记录 max(elapsed) 写入工具条目', () => {
  const msgs = runEventsToChatMessages([
    taskToolUse('call_K'),
    { type: 'tool_progress', tool_use_id: 'inner_1', parent_tool_use_id: 'call_K', elapsed_time_seconds: 300 },
    { type: 'tool_progress', tool_use_id: 'inner_1', parent_tool_use_id: 'call_K', elapsed_time_seconds: 510 },
    { type: 'tool_progress', tool_use_id: 'inner_1', parent_tool_use_id: 'call_K', elapsed_time_seconds: 120 },
  ]);
  assert.equal(msgs.length, 1);
  assert.equal(msgs[0].toolElapsedSeconds, 510);
});

test('无心跳覆盖的工具不写 toolElapsedSeconds', () => {
  const msgs = runEventsToChatMessages([taskToolUse('call_Q')]);
  assert.equal(msgs.length, 1);
  assert.equal(msgs[0].toolElapsedSeconds, undefined);
});

// ── 既有分支不回归 ───────────────────────────────────────────────────

test('session_ended 既有用例不回归', () => {
  const msgs = runEventsToChatMessages([{ type: 'session_ended', reason: 'idle' }]);
  assert.equal(msgs.length, 1);
  assert.equal(msgs[0].type, 'system');
  assert.match(msgs[0].content, /空闲/);
  assert.doesNotMatch(msgs[0].content, /\[session_ended\]/);
});

test('error/interrupted/cancelled 终态分支保持不变', () => {
  const msgs = runEventsToChatMessages([
    { type: 'error', error: 'Max turns (600) reached' },
    { type: 'interrupted', reason: 'user stop' },
    { type: 'cancelled', reason: 'cancel requested' },
  ]);
  assert.equal(msgs.length, 3);
  assert.equal(msgs[0].type, 'error');
  assert.match(msgs[0].content, /Max turns/);
  assert.equal(msgs[1].type, 'system');
  assert.match(msgs[1].content, /user stop/);
  assert.match(msgs[2].content, /cancel requested/);
});

test('result 终态标记 [success]/[error] 仍省略、其余内容照旧渲染', () => {
  const msgs = runEventsToChatMessages([
    { type: 'result', content: '[success]' },
    { type: 'result', content: '[error]' },
    { type: 'result', content: '自由文本终态' },
  ]);
  assert.equal(msgs.length, 1);
  assert.equal(msgs[0].content, '自由文本终态');
});

test('assistant/user/tool_use/tool_result 既有管线不回归', () => {
  const msgs = runEventsToChatMessages([
    {
      type: 'assistant',
      message: {
        content: [
          { type: 'text', text: '第一段回答' },
          { type: 'tool_use', id: 't1', name: 'Bash', input: { command: 'ls' } },
        ],
      },
    },
    { type: 'user', message: { content: [{ type: 'tool_result', tool_use_id: 't1', content: 'ok' }] } },
  ]);
  const types = msgs.map((m) => m.type);
  assert.ok(types.includes('assistant'));
  assert.ok(types.includes('tool'));
  const toolMsg = msgs.find((m) => m.type === 'tool');
  assert.equal(toolMsg?.toolResult?.content, 'ok');
});
