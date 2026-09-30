// thinking 时长/预览与显示开关（add-run-record-readability 3.3）。
// 零依赖，node 原生 type-stripping 加载 .ts 源。
// 运行：cd core/dashboard/static && node --test tests/thinkingScope.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { runEventsToChatMessages, thinkingPreviewText } from '../src/components/claude-msg/runEvents.ts';
import { groupConsecutiveTools, isToolGroupItem } from '../src/components/claude-msg/toolGrouping.ts';
import { formatThinkingLabel } from '../src/components/claude-msg/chatFormatting.ts';

function assistantEventAt(time, blocks) {
  return { type: 'assistant', timestamp: time, message: { content: blocks } };
}

const thinkingBlock = (text) => ({ type: 'thinking', thinking: text });
const textBlock = (text) => ({ type: 'text', text });
const bashBlock = (id, cmd) => ({ type: 'tool_use', id, name: 'Bash', input: { command: cmd } });

// ── 时长估算 ─────────────────────────────────────────────────────────

test('有相邻 assistant 时间戳时估算「已思考 N 秒」', () => {
  const msgs = runEventsToChatMessages([
    assistantEventAt('2026-09-22T05:12:24', [thinkingBlock('先看 queue.py 的派发逻辑'), bashBlock('t1', 'ls')]),
    assistantEventAt('2026-09-22T05:12:37', [textBlock('结论如下')]),
  ]);
  const thinking = msgs.find((m) => m.isThinking);
  assert.ok(thinking, 'thinking 条目应存在');
  assert.equal(thinking.thinkingSeconds, 13);
});

test('末尾无下一 assistant 事件时回退「已思考数秒」（不写字段）', () => {
  const msgs = runEventsToChatMessages([
    assistantEventAt('2026-09-22T05:12:24', [thinkingBlock('流末尾的思考'), textBlock('正文')]),
  ]);
  const thinking = msgs.find((m) => m.isThinking);
  assert.ok(thinking);
  assert.equal(thinking.thinkingSeconds, undefined);
});

test('时间戳差为负（乱序）时回退，不产生负数', () => {
  const msgs = runEventsToChatMessages([
    assistantEventAt('2026-09-22T05:12:37', [thinkingBlock('乱序思考'), textBlock('a')]),
    assistantEventAt('2026-09-22T05:12:24', [textBlock('b')]),
  ]);
  const thinking = msgs.find((m) => m.isThinking);
  assert.ok(thinking);
  assert.equal(thinking.thinkingSeconds, undefined);
});

test('时间戳缺失时回退', () => {
  const msgs = runEventsToChatMessages([
    { type: 'assistant', message: { content: [thinkingBlock('无时间戳'), textBlock('x')] } },
  ]);
  const thinking = msgs.find((m) => m.isThinking);
  assert.ok(thinking);
  assert.equal(thinking.thinkingSeconds, undefined);
});

// item 5828e59782f2：同事件 tool_use 的心跳观测耗时从估算差值中扣除，
// 工具执行时长不再计入「已思考 N 秒」
test('同事件工具的心跳观测耗时从估算差值中扣除', () => {
  const msgs = runEventsToChatMessages([
    assistantEventAt('2026-09-22T05:12:24', [thinkingBlock('长工具前的思考'), bashBlock('t1', 'ls')]),
    { type: 'tool_progress', tool_use_id: 't1', elapsed_time_seconds: 290 },
    assistantEventAt('2026-09-22T05:17:15', [textBlock('结论')]),
  ]);
  const thinking = msgs.find((m) => m.isThinking);
  assert.ok(thinking);
  // 差值 291s - 工具观测 290s ≈ 1s，不再把工具执行时长整体计入
  assert.equal(thinking.thinkingSeconds, 1);
});

// ── 首行预览 ─────────────────────────────────────────────────────────

test('预览取首个非空行，超长约 40 字符截断加省略号', () => {
  assert.equal(thinkingPreviewText('\n  第二行才是首行非空'), '第二行才是首行非空');
  const long = 'x'.repeat(100);
  const preview = thinkingPreviewText(long);
  assert.equal(preview.length, 41);
  assert.ok(preview.endsWith('…'));
  assert.equal(thinkingPreviewText('短预览'), '短预览');
  assert.equal(thinkingPreviewText(''), '');
});

test('runEventsToChatMessages 产出 thinkingPreview 字段', () => {
  const msgs = runEventsToChatMessages([
    assistantEventAt('2026-09-22T05:12:24', [thinkingBlock('先看 queue.py 的派发逻辑'), bashBlock('t1', 'ls')]),
    assistantEventAt('2026-09-22T05:12:37', [textBlock('结论')]),
  ]);
  const thinking = msgs.find((m) => m.isThinking);
  assert.equal(thinking.thinkingPreview, '先看 queue.py 的派发逻辑');
});

test('formatThinkingLabel 文案组合（时长段 · 预览段）与回退', () => {
  assert.equal(formatThinkingLabel(13, '先看 queue.py…'), '已思考 13 秒 · 先看 queue.py…');
  assert.equal(formatThinkingLabel(13), '已思考 13 秒');
  assert.equal(formatThinkingLabel(undefined), '已思考数秒');
  assert.equal(formatThinkingLabel(null), '已思考数秒');
  assert.equal(formatThinkingLabel(-5, '预览'), '已思考数秒 · 预览');
  assert.equal(formatThinkingLabel(0), '已思考数秒');
});

// ── 显示开关与无正文兜底 ─────────────────────────────────────────────

function mixedStream() {
  return [
    assistantEventAt('2026-09-22T05:00:01', [bashBlock('t1', 'ls')]),
    assistantEventAt('2026-09-22T05:00:02', [thinkingBlock('中间的思考')]),
    assistantEventAt('2026-09-22T05:00:03', [textBlock('这是正文')]),
    assistantEventAt('2026-09-22T05:00:04', [bashBlock('t2', 'pwd')]),
  ];
}

test('默认关闭（有正文流）：thinking 不渲染且不断组', () => {
  const msgs = runEventsToChatMessages(mixedStream(), false);
  assert.ok(!msgs.some((m) => m.isThinking), 'thinking 应被抑制');
  // 前后 Bash 中间隔 thinking：抑制后可参与分组（t1 与 t2 不相邻——中间还有
  // text 正文行，故不聚合；此处验证 thinking 位置本身不产生渲染项）
  assert.equal(msgs.some((m) => String(m.content || '') === '中间的思考'), false);
});

test('关闭开关时 thinking 位置不打断同类工具分组（有正文流，thinking 真被隐藏）', () => {
  // 修复 BUG-02 后「全程无正文」的流兜底强制渲染 thinking（可见即断组），
  // 本用例锚定的是隐藏路径，夹具须含非空正文
  const events = [
    assistantEventAt('2026-09-22T05:00:00', [textBlock('开场正文')]),
    assistantEventAt('2026-09-22T05:00:01', [bashBlock('t1', 'ls')]),
    assistantEventAt('2026-09-22T05:00:02', [thinkingBlock('思考')]),
    assistantEventAt('2026-09-22T05:00:03', [bashBlock('t2', 'pwd')]),
  ];
  const msgs = runEventsToChatMessages(events, false);
  assert.ok(!msgs.some((m) => m.isThinking), '有正文流开关关闭时 thinking 被抑制');
  const items = groupConsecutiveTools(msgs, false);
  const groups = items.filter(isToolGroupItem);
  assert.equal(groups.length, 1, '隐藏的 thinking 不打断同类分组');
  assert.equal(groups[0].messages.length, 2);
});

test('全程无正文（deepseek 系形态）时兜底强制渲染 thinking', () => {
  const events = [
    assistantEventAt('2026-09-22T05:00:01', [thinkingBlock('只有思考 A')]),
    assistantEventAt('2026-09-22T05:00:09', [thinkingBlock('只有思考 B')]),
  ];
  const msgs = runEventsToChatMessages(events, false);
  const thinking = msgs.filter((m) => m.isThinking);
  assert.equal(thinking.length, 1, '两个事件的 thinking 合并为一条且强制渲染');
  assert.match(thinking[0].content, /只有思考 A/);
  assert.match(thinking[0].content, /只有思考 B/);
});

test('开关打开时恢复渲染 thinking（默认参数 true 行为不变）', () => {
  const events = mixedStream();
  const msgs = runEventsToChatMessages(events, true);
  assert.ok(msgs.some((m) => m.isThinking));
  // 既有直调方（SessionPanel.tsx:332）不传参：默认 true 行为不变
  const msgsDefault = runEventsToChatMessages(events);
  assert.ok(msgsDefault.some((m) => m.isThinking));
});

test('流式 thinking_tokens 旧形态同样受开关控制', () => {
  const events = [
    { type: 'system', subtype: 'thinking_tokens', content: '流式思考片段' },
    assistantEventAt('2026-09-22T05:00:03', [textBlock('正文')]),
  ];
  assert.equal(runEventsToChatMessages(events, false).filter((m) => m.isThinking).length, 0);
  assert.equal(runEventsToChatMessages(events, true).filter((m) => m.isThinking).length, 1);
});

// ── 无正文兜底强制渲染标记（BUG-02 回归锚定：兜底须传导到渲染层） ──────

test('全程无正文流 + 开关关闭：兜底产出的 thinking 带 thinkingForced 标记', () => {
  const events = [
    assistantEventAt('2026-09-22T05:12:24', [thinkingBlock('尾部收尾思考')]),
    assistantEventAt('2026-09-22T05:12:29', [thinkingBlock('真正的最后思考')]),
  ];
  const msgs = runEventsToChatMessages(events, false);
  const thinkings = msgs.filter((m) => m.isThinking);
  assert.ok(thinkings.length >= 1, '兜底应强制产出 thinking 条目');
  for (const m of thinkings) {
    assert.equal(m.thinkingForced, true, '兜底消息必须带 thinkingForced 标记，渲染层据此豁免隐藏');
  }
});

test('流内有非空正文 + 开关关闭：thinking 不产出（无兜底，无标记）', () => {
  const events = [
    assistantEventAt('2026-09-22T05:12:24', [thinkingBlock('被开关关闭的思考'), textBlock('正文结论')]),
  ];
  const msgs = runEventsToChatMessages(events, false);
  assert.equal(msgs.filter((m) => m.isThinking).length, 0);
  assert.ok(msgs.some((m) => m.type === 'assistant' && !m.isThinking));
});

test('开关打开时 thinking 不带 thinkingForced（正常渲染路径）', () => {
  const events = [assistantEventAt('2026-09-22T05:12:24', [thinkingBlock('思考')])];
  const thinking = runEventsToChatMessages(events, true).find((m) => m.isThinking);
  assert.ok(thinking);
  assert.equal(thinking.thinkingForced, undefined);
});

test('groupConsecutiveTools：兜底强制渲染的 thinking 照常打断同类分组', () => {
  const a = { type: 'tool', isToolUse: true, toolName: 'Bash', toolInput: { command: 'echo a' }, toolId: 'f1', timestamp: '2026-09-22T05:00:01' };
  const t = { type: 'assistant', isThinking: true, content: '思考', timestamp: '2026-09-22T05:00:02', thinkingForced: true };
  const b = { type: 'tool', isToolUse: true, toolName: 'Bash', toolInput: { command: 'echo b' }, toolId: 'f2', timestamp: '2026-09-22T05:00:03' };
  const items = groupConsecutiveTools([a, t, b], false);
  assert.equal(items.length, 3, '强制渲染的 thinking 可见，须断组');
  assert.ok(!items.some(isToolGroupItem), '断组后阈值不足不聚合');
});
