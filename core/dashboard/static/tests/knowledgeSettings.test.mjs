// 知识真相源维护开关渲染语义单元测试（add-knowledge-atlas-maintenance 任务 1.2）。
// 零依赖，node 原生 type-stripping 加载 .ts。
// 运行：cd core/dashboard/static && node --test tests/knowledgeSettings.test.mjs
//
// 覆盖：
// - config.knowledge 段（缺失/部分/关闭/脏形状）→ 开关状态映射；
// - 开关状态 → 保存载荷 knowledge 段（与后端局部段合并语义对齐）；
// - 说明文案非空且含关键信息（车道行为 / graphify 安装命令）。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  knowledgeSectionFromSwitches,
  knowledgeSwitchDesc,
  knowledgeSwitchesFromConfig,
} from '../src/pages/settings/knowledgeSettings.ts';

// ── 段缺失/脏形状 → 缺省全开（与 core/config.py get_knowledge_config 同口径） ──

test('config 无 knowledge 段时两开关默认开启', () => {
  const s = knowledgeSwitchesFromConfig(undefined);
  assert.equal(s.auditEnabled, true);
  assert.equal(s.graphEnabled, true);
});

test('非对象段（后端降级为 null/标量）不崩且默认开启', () => {
  for (const bad of [null, 3, 'x', []]) {
    const s = knowledgeSwitchesFromConfig(bad);
    assert.equal(s.auditEnabled, true);
    assert.equal(s.graphEnabled, true);
  }
});

test('显式 false 关闭对应开关，缺键保持开启', () => {
  const s = knowledgeSwitchesFromConfig({ audit_enabled: false });
  assert.equal(s.auditEnabled, false);
  assert.equal(s.graphEnabled, true);
});

test('非法值（字符串/数字非 false）按开启处理（与后端回退缺省同口径）', () => {
  const s = knowledgeSwitchesFromConfig({ audit_enabled: 'yes', graph_enabled: 1 });
  assert.equal(s.auditEnabled, true);
  assert.equal(s.graphEnabled, true);
});

// ── 保存载荷往返 ──────────────────────────────────────────────────────

test('开关状态 → knowledge 段保存载荷显式落两键', () => {
  const payload = knowledgeSectionFromSwitches({
    auditEnabled: true,
    graphEnabled: false,
  });
  assert.deepEqual(payload, {
    knowledge: { audit_enabled: true, graph_enabled: false },
  });
});

test('段映射 → 载荷往返保真', () => {
  const round = knowledgeSectionFromSwitches(
    knowledgeSwitchesFromConfig({ audit_enabled: false, graph_enabled: false }),
  );
  assert.deepEqual(round, {
    knowledge: { audit_enabled: false, graph_enabled: false },
  });
});

// ── 说明文案（交互契约：设置页控件必须带说明） ────────────────────────

test('audit 开关说明含体检行为与报告落点', () => {
  const desc = knowledgeSwitchDesc('audit');
  assert.ok(desc.includes('体检'));
  assert.ok(desc.includes('knowledge_audit_report.md'));
});

test('graph 开关说明含 graphify 人工安装步骤', () => {
  const desc = knowledgeSwitchDesc('graph');
  assert.ok(desc.includes('graphify'));
  assert.ok(desc.includes('uv tool install graphifyy'));
});
