## ADDED Requirements

### Requirement: alert-resolve 端点一次选择完成处置闭环

系统 MUST 新增端点 `POST /api/alert-resolve`（`core/dashboard/routes/alert_routes.py`），接受 `{project, alert_id, choice_id, note?}`。端点 MUST 按序完成且原子性表现为一次调用：(1) 校验告警存在且未 handled，按 alert 的 `signal_type` 从注册表校验 `choice_id` 合法；(2) 执行 choice 映射的后端动作（复用 `core/dashboard/data/admin_actions.py` 既有动词或新增裁决动词）；(3) 将 spec 状态机推进到该裁决的目标终态（含冻结解除、计数器处置、error 清理）；(4) `mark_handled` 该告警并落处置留痕（复用 DISPOSITION 记录：choice_id、note、执行结果）。任一步失败 MUST 返回结构化错误且不标记 handled（已执行的前序动作 MUST 在错误信息中如实报告，不做虚假回滚声明）。

#### Scenario: 选择即完整闭环
- **WHEN** 对 `impl_budget_exhausted` 冻结告警选择 `force_advance` 并附 note
- **THEN** 单次调用后：spec 状态推进到 done（解冻、error 清空）、告警标记 handled、产生含 choice_id 与 note 的处置留痕记录

#### Scenario: 非法选择被拒绝
- **WHEN** 对 `signal_type=token_budget` 的告警提交 `choice_id=force_advance`（不在该信号选项集中）
- **THEN** 返回 400 级错误说明合法选项集，spec 状态与告警 handled 状态均不变

#### Scenario: 重复处置被拒绝
- **WHEN** 对已 handled 的告警再次提交 alert-resolve
- **THEN** 返回冲突错误，不重复执行动作

#### Scenario: 动作失败不虚假标记成功
- **WHEN** choice 映射的后端动作执行抛出异常
- **THEN** 返回错误并附已执行步骤说明，告警保持未 handled，spec 状态保持可重试裁决

### Requirement: 处置留痕进 admin 活动记录

每次 alert-resolve 成功 MUST 在 `admin_alerts.json` 落一条 `kind=disposition` 记录，内容包含：`signal_type`、`spec`、`choice_id`、`note`（人工备注，可空）、执行动作摘要。该记录 MUST 对 dashboard admin 活动区可见，作为裁决审计轨迹；MUST 同时满足既有「清除告警 ≠ 处置留痕」的治理要求（人工下拉处置产生的留痕不依赖手写四段散文模板）。

#### Scenario: 处置记录含结构化字段
- **WHEN** 人工通过下拉选择 `manual_fixed_reverify` 完成
- **THEN** 产生的 disposition 记录含 `choice_id=manual_fixed_reverify`、`note` 原文与动作执行摘要，并可在 admin 活动区查到
