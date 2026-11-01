// type:"prompt" 事件流渲染静默锚定（add-run-prompt-viewer 3.1）。
// 零依赖，node 原生 type-stripping 直载 .ts 源——需 Node ≥22.18（23.6+ 同样
// 默认开启；22.6–22.17 须显式 --experimental-strip-types；20.x 无此能力会以
// ERR_UNKNOWN_FILE_EXTENSION 失败）。形态对齐 runStreamNoise.test.mjs。
// 运行：cd core/dashboard/static && node --test tests/runPromptSilence.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { runEventsToChatMessages } from '../src/components/claude-msg/runEvents.ts';
import { groupConsecutiveTools } from '../src/components/claude-msg/toolGrouping.ts';

// 事件构造辅助：SDK 结构化事件为 type:"system" + subtype 形态
const sys = (subtype, extra = {}) => ({ type: 'system', subtype, ...extra });

const promptEvent = (text = '完整注入提示词全文') => ({
  type: 'prompt',
  text,
  timestamp: '2026-01-01T00:00:00+00:00',
});

const tool = (id) => ({
  type: 'assistant',
  message: { content: [{ type: 'tool_use', id, name: 'Bash', input: { command: `cmd ${id}` } }] },
});

test('prompt 事件零产出：顶层 type 形态不产出行（含/不含 text 载荷）', () => {
  assert.equal(runEventsToChatMessages([promptEvent()]).length, 0);
  assert.equal(runEventsToChatMessages([{ type: 'prompt' }]).length, 0);
  // 大提示词载荷同样静默（不因载荷非空回退渲染）
  assert.equal(runEventsToChatMessages([promptEvent('x'.repeat(50000))]).length, 0);
});

test('prompt 事件零产出：system+subtype 形态不产出行（kind 归一化前置）', () => {
  assert.equal(runEventsToChatMessages([sys('prompt')]).length, 0);
});

test('prompt 行穿插不打断连续工具分组（等效不可见分隔符）', () => {
  const events = [
    tool('a'),
    promptEvent(),
    tool('b'),
    sys('status'),
    promptEvent('再插一条'),
    tool('c'),
  ];
  const items = groupConsecutiveTools(runEventsToChatMessages(events));
  assert.equal(items.length, 1);
  assert.equal(items[0].toolName, 'Bash');
  assert.equal(items[0].messages.length, 3);
});

test('prompt 行出现在流头部/中部/尾部均零产出且不回归既有管线', () => {
  const events = [
    promptEvent(),
    { type: 'system', subtype: 'init' },
    {
      type: 'assistant',
      message: { content: [{ type: 'text', text: '第一段回答' }] },
    },
    promptEvent(),
    { type: 'result', content: '自由文本终态' },
  ];
  const msgs = runEventsToChatMessages(events);
  assert.equal(msgs.length, 2);
  assert.equal(msgs[0].type, 'assistant');
  assert.equal(msgs[0].content, '第一段回答');
  assert.equal(msgs[1].type, 'system');
  assert.equal(msgs[1].content, '自由文本终态');
  // 提示词全文不得以任何形态泄漏进消息流
  const texts = msgs.map((m) => String(m.content || '')).join('|');
  assert.ok(!texts.includes('完整注入提示词全文'));
});
