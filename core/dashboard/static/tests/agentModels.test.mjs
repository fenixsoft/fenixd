// cloneRoleValue 单元测试（零依赖，node 原生 type-stripping 加载 .ts）。
// 运行：cd core/dashboard/static && node --test tests/agentModels.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { cloneRoleValue } from '../src/utils/agentModels.ts';

test('深拷贝 rows：改动副本不影响源（复制后编辑源卡片不串改剪贴板）', () => {
  const src = { roleModel: 'm', rows: [{ provider: 'p', model: 'x' }] };
  const copy = cloneRoleValue(src);
  copy.rows[0].provider = 'changed';
  copy.rows.push({ provider: 'extra', model: '' });
  assert.equal(src.rows[0].provider, 'p');
  assert.equal(src.rows.length, 1);
});

test('保留角色级默认模型与多行 Provider 链，且 rows 为新引用', () => {
  const src = {
    roleModel: 'default-m',
    rows: [
      { provider: 'a', model: '1' },
      { provider: 'b', model: '' },
    ],
  };
  const copy = cloneRoleValue(src);
  assert.deepEqual(copy, src);
  assert.notEqual(copy.rows, src.rows);
  assert.notEqual(copy.rows[0], src.rows[0]);
});

test('健壮性：rows 缺省时归一为空数组，roleModel 归为字符串', () => {
  assert.deepEqual(cloneRoleValue({ roleModel: '' }), { roleModel: '', rows: [] });
  assert.deepEqual(cloneRoleValue(undefined), { roleModel: '', rows: [] });
});

test('roleKey 保留：克隆/粘贴不丢角色键（item 042e1dc46cb4）', () => {
  const src = { roleKey: 'verifier', roleModel: 'm', rows: [{ provider: 'p', model: '' }] };
  const copy = cloneRoleValue(src);
  assert.equal(copy.roleKey, 'verifier');
  // 无 roleKey 的源不引入 roleKey: undefined 键（既有 deepEqual 语义不变）
  assert.deepEqual(cloneRoleValue({ roleModel: '', rows: [] }), { roleModel: '', rows: [] });
});

// ── add-agent-model-quick-assign 6.1：快速分配纯函数 ──
import { buildQuickAssignAssignment, buildQuickAssignTargets } from '../src/utils/agentModels.ts';

test('buildQuickAssignAssignment：trim、空行过滤、model 留空省略、保持行序', () => {
  const a = buildQuickAssignAssignment(
    '  deepseek-v4-pro  ',
    [
      { provider: ' volc-engine ', model: ' deepseek-v4-pro ' },
      { provider: '  ', model: 'x' }, // provider 空 → 丢弃
      { provider: 'bigmodel.cn', model: '' }, // 元素级 model 留空
    ],
  );
  assert.deepEqual(a, {
    model: 'deepseek-v4-pro',
    provider: [
      { provider: 'volc-engine', model: 'deepseek-v4-pro' },
      { provider: 'bigmodel.cn', model: '' },
    ],
  });
});

test('buildQuickAssignAssignment：角色级 model 留空则省略该字段', () => {
  const a = buildQuickAssignAssignment('', [{ provider: 'p1', model: '' }]);
  assert.deepEqual(a, { provider: [{ provider: 'p1', model: '' }] });
  assert.ok(!('model' in a));
});

test('buildQuickAssignTargets：本作用域展开（无项目 → user；有项目 → project）', () => {
  assert.deepEqual(buildQuickAssignTargets(true, undefined, []), [{ scope: 'user' }]);
  assert.deepEqual(buildQuickAssignTargets(true, 'proj-a', []), [
    { scope: 'project', project: 'proj-a' },
  ]);
});

test('buildQuickAssignTargets：指定项目去重、剔除空串、本作用域在前', () => {
  const t = buildQuickAssignTargets(true, 'proj-a', ['proj-b', ' proj-b ', '', 'proj-a', 'proj-c']);
  assert.deepEqual(t, [
    { scope: 'project', project: 'proj-a' },
    { scope: 'project', project: 'proj-b' },
    { scope: 'project', project: 'proj-c' },
  ]);
});

test('buildQuickAssignTargets：本作用域不勾选且未选项目 → 空数组（应用按钮 disabled）', () => {
  assert.deepEqual(buildQuickAssignTargets(false, undefined, []), []);
  assert.deepEqual(buildQuickAssignTargets(false, 'proj-a', []), []);
});
