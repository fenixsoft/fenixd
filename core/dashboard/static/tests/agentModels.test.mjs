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
