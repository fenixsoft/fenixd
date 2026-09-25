// session-composer 纯逻辑单元测试（零 React / 零 DOM 依赖，node 原生
// type-stripping 直载 .ts 源）。
// 运行：cd core/dashboard/static && node --test tests/session-composer.test.mjs
//
// 覆盖 tasks.md 2.5 要求的四类用例：
//  - 草稿存取（chatStorage + mock localStorage）
//  - @ 提及片段替换（matchFileMention / replaceFileMention）
//  - 斜杠触发条件（matchSlashTrigger：行首 / 空白后 / 代码块内不触发）
//  - debounce（createTrailingDebounce 真实短延时断言）
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  matchFileMention,
  matchSlashTrigger,
  replaceFileMention,
  createTrailingDebounce,
  COMMAND_QUERY_DEBOUNCE_MS,
  toSlashCommands,
  filterSlashCommands,
  sortCommandsByUsage,
  frequentCommands,
} from '../src/components/claude-composer/composerLogic.ts';

// chatStorage 顶层不触碰 localStorage（仅函数调用时查找），但为稳妥起见
// 在 mock 就绪后再动态加载。
const store = new Map();
globalThis.localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: (k) => store.delete(k),
  getOwnPropertyNames: () => [...store.keys()],
};
const { draftKey, commandHistoryKey, readDraft, writeDraft, clearDraft, readCommandHistory, saveCommandHistory } =
  await import('../src/components/claude-composer/chatStorage.ts');

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// ── 草稿存取 ───────────────────────────────────────────────────────────────

test('草稿键按 project 命名（draft_input_<project> / command_history_<project>）', () => {
  assert.equal(draftKey('proj-a'), 'draft_input_proj-a');
  assert.equal(commandHistoryKey('proj-a'), 'command_history_proj-a');
});

test('草稿写入后可读回，clearDraft 清空后归空串', () => {
  writeDraft('proj-a', '待发送的草稿');
  assert.equal(readDraft('proj-a'), '待发送的草稿');
  clearDraft('proj-a');
  assert.equal(readDraft('proj-a'), '');
});

test('草稿按项目隔离：proj-a 的草稿不出现在 proj-b', () => {
  writeDraft('proj-a', 'A 的草稿');
  writeDraft('proj-b', 'B 的草稿');
  assert.equal(readDraft('proj-a'), 'A 的草稿');
  assert.equal(readDraft('proj-b'), 'B 的草稿');
  clearDraft('proj-a');
  assert.equal(readDraft('proj-b'), 'B 的草稿');
});

test('从未写过的项目草稿读出空串（不出错）', () => {
  assert.equal(readDraft('proj-never'), '');
});

test('命令频次历史：保存后可读回，且与草稿键互不串扰', () => {
  saveCommandHistory('proj-a', { '/compact': 2, '/review': 1 });
  assert.deepEqual(readCommandHistory('proj-a'), { '/compact': 2, '/review': 1 });
  assert.deepEqual(readCommandHistory('proj-b'), {});
  // proj-a 写频次不影响其草稿
  writeDraft('proj-a', '草稿仍在');
  saveCommandHistory('proj-a', { '/compact': 3 });
  assert.equal(readDraft('proj-a'), '草稿仍在');
  assert.deepEqual(readCommandHistory('proj-a'), { '/compact': 3 });
});

test('频次历史损坏（非 JSON / 非对象）时归空对象，不抛错', () => {
  localStorage.setItem(commandHistoryKey('proj-bad'), 'not-json{{');
  assert.deepEqual(readCommandHistory('proj-bad'), {});
  localStorage.setItem(commandHistoryKey('proj-bad'), '[1,2]');
  assert.deepEqual(readCommandHistory('proj-bad'), {});
});

// ── @ 提及：触发判定与片段替换 ──────────────────────────────────────────────

test('@ 提及触发：光标前最后一个 @，返回位置与查询词', () => {
  const m = matchFileMention('看下 @src');
  assert.equal(m.atIndex, 3);
  assert.equal(m.query, 'src');
});

test('@ 提及不触发：@ 后出现空格、或输入无 @', () => {
  assert.equal(matchFileMention('看 @src 文件'), null);
  assert.equal(matchFileMention('邮箱 a@b.com '), null);
  assert.equal(matchFileMention('没有任何提及'), null);
});

test('@ 片段替换：`@src` → `@src/app.tsx`（保留 @ 前缀），光标落在插入文本末尾', () => {
  const input = '看 @src 这段';
  // '@' 在 index 2，'@src' 之后是空格
  const { text, cursor } = replaceFileMention(input, 2, 'src/app.tsx');
  assert.equal(text, '看 @src/app.tsx 这段');
  // before(2) + '@'(1) + path(11) + ' '(1) = 15，指向'这'
  assert.equal(cursor, 15);
});

test('@ 片段替换：光标前一个字符是路径后的分隔空格', () => {
  const { text, cursor } = replaceFileMention('@src', 0, 'src/app.tsx');
  assert.equal(text, '@src/app.tsx ');
  // before(0) + '@'(1) + path(11) + ' '(1) = 13
  assert.equal(cursor, 13);
  assert.equal(text.slice(cursor - 1, cursor), ' ');
});

test('@ 片段替换：查询词位于输入末尾（无尾部文本）时追加路径与空格', () => {
  const { text, cursor } = replaceFileMention('请看 @re', 3, 'README.md');
  assert.equal(text, '请看 @README.md ');
  assert.equal(cursor, text.length);
});

// ── 斜杠触发条件 ───────────────────────────────────────────────────────────

test('斜杠触发：行首输入 `/` 命中，位置 0', () => {
  const m = matchSlashTrigger('/comp');
  assert.deepEqual(m, { position: 0, query: 'comp' });
});

test('斜杠触发：空白字符之后的 `/` 命中，返回 `/` 的绝对位置', () => {
  const m = matchSlashTrigger('帮我 /rev');
  // '/' 在 index 3
  assert.deepEqual(m, { position: 3, query: 'rev' });
});

test('斜杠不触发：普通文本中的 `/`（前一个字符非空白）', () => {
  assert.equal(matchSlashTrigger('路径 a/b'), null);
  assert.equal(matchSlashTrigger('https://example.com'), null);
});

test('斜杠不触发：纯 `/` 前无任何上下文以外的情况——空文本 / 纯空白', () => {
  assert.equal(matchSlashTrigger(''), null);
  assert.equal(matchSlashTrigger('   '), null);
});

test('斜杠不触发：``` 代码块内（奇数围栏）', () => {
  assert.equal(matchSlashTrigger('```\n/comp'), null);
  // 偶数围栏（已闭合）恢复触发；'/' 在 index 13
  assert.deepEqual(matchSlashTrigger('```\ncode\n```\n/comp'), { position: 13, query: 'comp' });
});

test('斜杠查询词为空（仅 `/`）也算触发，query 为空串', () => {
  assert.deepEqual(matchSlashTrigger('/'), { position: 0, query: '' });
});

// ── debounce ───────────────────────────────────────────────────────────────

test('debounce：delay 内连续 call 只执行最后一次（真实短延时）', async () => {
  const calls = [];
  const d = createTrailingDebounce((v) => calls.push(v), 40);
  d.call('a');
  d.call('b');
  d.call('c');
  await sleep(15);
  assert.deepEqual(calls, [], 'delay 未到不执行');
  await sleep(60);
  assert.deepEqual(calls, ['c'], '只保留最后一次调用参数');
});

test('debounce：cancel 后不再执行', async () => {
  const calls = [];
  const d = createTrailingDebounce((v) => calls.push(v), 30);
  d.call('x');
  d.cancel();
  await sleep(60);
  assert.deepEqual(calls, []);
});

test('斜杠查询 debounce 常量为 150ms（spec 契约）', () => {
  assert.equal(COMMAND_QUERY_DEBOUNCE_MS, 150);
});

// ── 候选规整 / 过滤 / 排序 ──────────────────────────────────────────────────

test('toSlashCommands：裸名补 `/` 前缀，skills 标记为 skill 类型', () => {
  const cmds = toSlashCommands(['compact', '/review'], ['my-skill']);
  assert.deepEqual(cmds, [
    { name: '/compact', type: 'builtin' },
    { name: '/review', type: 'builtin' },
    { name: '/my-skill', namespace: 'skill', type: 'skill' },
  ]);
});

test('filterSlashCommands：名称前缀优先，其次子串，空查询返回全部', () => {
  const all = [
    { name: '/compact' },
    { name: '/config' },
    { name: '/review' },
  ];
  assert.deepEqual(filterSlashCommands(all, ''), all);
  assert.deepEqual(filterSlashCommands(all, 'comp'), [{ name: '/compact' }]);
  // 无前缀命中时退化为子串
  assert.deepEqual(filterSlashCommands(all, 'view'), [{ name: '/review' }]);
  assert.deepEqual(filterSlashCommands(all, '不存在'), []);
});

test('sortCommandsByUsage / frequentCommands：按频次降序、稳定排序、频次 0 不进常用', () => {
  const cmds = [{ name: '/a' }, { name: '/b' }, { name: '/c' }, { name: '/d' }];
  const history = { '/b': 3, '/c': 1 };
  assert.deepEqual(
    sortCommandsByUsage(cmds, history).map((c) => c.name),
    ['/b', '/c', '/a', '/d'],
  );
  const frequent = frequentCommands(cmds, history);
  assert.deepEqual(frequent.map((c) => c.name), ['/b', '/c']);
  assert.equal(frequent[0].usageCount, 3);
  assert.deepEqual(frequentCommands(cmds, {}), []);
});
