// runEventsToChatMessages 会话终态分支单元测试（dashboard-live-session 5.5）。
// 零依赖，node 原生 type-stripping 加载 .ts 源。
// 运行：cd core/dashboard/static && node --test tests/sessionEvents.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { runEventsToChatMessages } from '../src/components/claude-msg/runEvents.ts';

// session_ended 事件：三种 reason 渲染为明确中文系统行（非 fallback [session_ended]）
test('session_ended reason=idle 渲染为中文系统行', () => {
  const msgs = runEventsToChatMessages([
    { type: 'session_ended', session_id: 's1', reason: 'idle' },
  ]);
  assert.equal(msgs.length, 1);
  assert.equal(msgs[0].type, 'system');
  assert.match(msgs[0].content, /空闲/);
  assert.doesNotMatch(msgs[0].content, /\[session_ended\]/);
});

test('session_ended reason=process_exit 渲染为中文系统行', () => {
  const msgs = runEventsToChatMessages([
    { type: 'session_ended', session_id: 's1', reason: 'process_exit' },
  ]);
  assert.equal(msgs.length, 1);
  assert.match(msgs[0].content, /进程已退出/);
  assert.doesNotMatch(msgs[0].content, /\[session_ended\]/);
});

test('session_ended reason=user 渲染为中文系统行', () => {
  const msgs = runEventsToChatMessages([
    { type: 'session_ended', session_id: 's1', reason: 'user' },
  ]);
  assert.equal(msgs.length, 1);
  assert.match(msgs[0].content, /已停止/);
  assert.doesNotMatch(msgs[0].content, /\[session_ended\]/);
});

test('session_ended 未知 reason 渲染为带 reason 的中文行', () => {
  const msgs = runEventsToChatMessages([
    { type: 'session_ended', session_id: 's1', reason: 'weird' },
  ]);
  assert.equal(msgs.length, 1);
  assert.match(msgs[0].content, /weird/);
  assert.doesNotMatch(msgs[0].content, /\[session_ended\]/);
});

// 既有 run 事件分支不回归
test('assistant / tool_use / tool_result 既有分支不回归', () => {
  const msgs = runEventsToChatMessages([
    {
      type: 'assistant',
      message: {
        content: [
          { type: 'thinking', thinking: '思考中...' },
          { type: 'text', text: '第一段回答' },
          { type: 'tool_use', id: 't1', name: 'Bash', input: { command: 'ls' } },
        ],
      },
    },
    {
      type: 'user',
      message: {
        content: [{ type: 'tool_result', tool_use_id: 't1', content: 'ok' }],
      },
    },
    {
      type: 'user',
      message: {
        role: 'user',
        content: [{ type: 'text', text: '客户提问' }],
      },
    },
  ]);
  // thinking + text + tool + tool_result + user 文本
  const types = msgs.map((m) => m.type);
  assert.ok(types.includes('assistant'));
  assert.ok(types.includes('tool'));
  assert.ok(types.includes('user'));
  const texts = msgs.map((m) => String(m.content || '')).join('|');
  assert.match(texts, /第一段回答/);
  assert.match(texts, /客户提问/);
  // tool_result 已回填到 tool 消息
  const toolMsg = msgs.find((m) => m.type === 'tool');
  assert.equal(toolMsg?.toolResult?.content, 'ok');
});

// user 回显事件（isReplay，块数组无顶层 content）应渲染出文本（D1 前端义务）
test('isReplay 回显 user 事件渲染为文本行（非空气泡）', () => {
  const msgs = runEventsToChatMessages([
    {
      type: 'user',
      isReplay: true,
      uuid: 'u1',
      message: {
        role: 'user',
        content: [{ type: 'text', text: '你好，帮我看看代码' }],
      },
    },
  ]);
  assert.equal(msgs.length, 1);
  assert.equal(msgs[0].type, 'user');
  assert.equal(msgs[0].content, '你好，帮我看看代码');
});

// 普通 user 事件顶层字符串 content 形态保持
test('顶层字符串 content 的 user 事件不回归', () => {
  const msgs = runEventsToChatMessages([
    { type: 'user', content: '旧形态纯文本提问' },
  ]);
  assert.equal(msgs.length, 1);
  assert.equal(msgs[0].type, 'user');
  assert.equal(msgs[0].content, '旧形态纯文本提问');
});