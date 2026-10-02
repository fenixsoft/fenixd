## ADDED Requirements

### Requirement: 机械快道裁决产物必须带来源戳

`core/pm_engine/verification/judge_gate.py` 的 `_all_green_fast_path` 写 `.fenix/verify-progress/<spec>/.fenix-run-result.json` 的 payload MUST 补 `"role": "verifier"` 字段（保留既有 `mechanical: true`、`spec`、`status`、`bugs`、`summary`）。背景：读侧 `_verifier_result_is_stale`（`report_gate.py:154`）对 role 缺失一律判「不采信」，机械快道产物当前缺 role 戳，导致同 SPEC 在飞 LLM verifier 完成时该文件必然被拒（2026-09-24 事故误判土壤）。

语义约束：

- 补戳后快道产物对读侧是合法的「验证车道产物」，`mechanical: true` 保留机械来源的可辨识性；
- 跨 spec 防护不变：`spec` 戳不符仍拒（`_verifier_result_is_stale` L157-159）；
- mtime 判据不变：文件早于在飞 run 启动时刻 5 秒以上仍判「本轮验证器未曾写回」；
- `core/verify_report.py` 等只读消费方按多余键兼容，无需改动。

#### Scenario: 快道产物通过读侧归属校验

- **WHEN** `_all_green_fast_path` 写出快道裁决文件后，同 SPEC 的结果读取方（`_read_verdict` / `_read_verifier_result`）读取该文件
- **THEN** role 校验通过（role=verifier），status=verified 正常读取，不再因 role 缺失返回 foreign-role

#### Scenario: 同轮在飞 LLM verifier 不再误判快道产物为异源

- **WHEN** 快道已写裁决（带 role 戳、mtime 晚于在飞 LLM verifier 的 run_id 内嵌启动时刻减 5 秒），该 LLM verifier 完成并做 stale 校验
- **THEN** 校验通过（role/spec 戳/mtime 均合法），结果按既有 D6 状态判据正常应用或丢弃，不落入 stale/foreign 回退分支

#### Scenario: 跨 spec 残留仍被拒绝

- **WHEN** 结果文件的 `spec` 戳与当前 SPEC 不符（即使带 role=verifier）
- **THEN** `_verifier_result_is_stale` 仍判不采信，行为与现状一致
