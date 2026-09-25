// codeFixGuidance 纯逻辑单元测试（零 React / 零 DOM 依赖，node 原生
// type-stripping 直载 .ts 源，模式同 session-composer.test.mjs）。
// 运行：cd core/dashboard/static && node --test tests/codeFixGuidance.test.mjs
//
// 覆盖（2026-09-25 用户要求「blocked 不能仅提示阻塞，须明确如何处理」）：
//  - 已知 reason → 人类可读原因 + 处置指引（重点：wip_overlap_at_select
//    必须点名「提交或 stash」这一用户动作）
//  - 未知/空 reason → 宁严勿松回退（原码透传 + 需人工排查，不静默）
//  - blockedReasonDisplay：已知带原码括注、未知原样回显
//  - 后端 code_fix.py 全部 blocked 写入点的 reason 键覆盖盘点
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { blockedReasonInfo, blockedReasonDisplay } from '../src/pages/projects/components/codeFixGuidance.ts';

test('wip_overlap_at_select 给出「提交或 stash」处置指引', () => {
  const info = blockedReasonInfo('wip_overlap_at_select');
  assert.match(info.label, /未提交改动/);
  assert.match(info.guidance, /提交或 stash/);
  assert.match(info.guidance, /自动恢复/);
});

test('selfheal 等待类 reason 指引为「无需处理」语义', () => {
  for (const r of ['failed_batch_retained', 'wip_gate_blocked']) {
    const info = blockedReasonInfo(r);
    assert.match(info.guidance, /无需处理/, `${r} 应标明无需人工介入`);
  }
});

test('disabled 指引指向重新打开开关', () => {
  const info = blockedReasonInfo('disabled');
  assert.match(info.guidance, /开关/);
});

test('契约缺失类 reason 指引指向 verify.yaml', () => {
  for (const r of ['regression_contract_missing', 'regression_section_missing']) {
    const info = blockedReasonInfo(r);
    assert.match(info.guidance, /verify\.yaml/, `${r} 应指向 verify.yaml`);
  }
});

test('未知 reason 宁严勿松：原码透传 + 需人工排查（不静默）', () => {
  const info = blockedReasonInfo('some_future_reason');
  assert.equal(info.label, 'some_future_reason');
  assert.equal(info.guidance, '需人工排查');
});

test('空/缺省 reason 回退「未知原因」而非 undefined 串进文案', () => {
  for (const r of [null, undefined, '']) {
    const info = blockedReasonInfo(r);
    assert.equal(info.label, '未知原因');
    assert.equal(info.guidance, '需人工排查');
    assert.equal(blockedReasonDisplay(r), '未知原因');
  }
});

test('blockedReasonDisplay：已知 reason 带原码括注，未知原样回显', () => {
  assert.equal(
    blockedReasonDisplay('wip_overlap_at_select'),
    '主树有未提交改动与本批待修文件重叠，整批已推迟（wip_overlap_at_select）',
  );
  assert.equal(blockedReasonDisplay('mystery'), 'mystery');
});

test('后端 blocked 写入点 reason 全集均有映射（键漂移盘点）', () => {
  // 与 core/code_fix.py 2026-09-25 盘点的全部 blocked reason 同源；
  // 后端新增 reason 时此处会因 blockedReasonInfo 回退仍可用，但应补映射。
  const backendReasons = [
    'disabled',
    'failed_batch_retained',
    'failed_batch_maxed',
    'wip_gate_blocked',
    'wip_overlap_at_select',
    'regression_contract_missing',
    'regression_section_missing',
  ];
  for (const r of backendReasons) {
    assert.notEqual(blockedReasonDisplay(r), r, `${r} 应有人类可读文案而非原码回显`);
  }
});
