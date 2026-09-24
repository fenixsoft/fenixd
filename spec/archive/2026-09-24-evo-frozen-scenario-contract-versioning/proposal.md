# Proposal: frozen-scenario-contract-versioning

## 问题

场景验收契约升级（新增校验规则，如「web 场景必须含 navigate（绝对 URL 打开）步骤」）后，已冻结的存量场景集因生成于旧契约之下、过不了新规则验收 → 被读端判为 corrupt（冻结场景文件损坏/验收失败），spec 置 blocked 待人工裁决「删除冻结文件批准重新出题」或「手动修复」。每次契约演化都可能触发整轮验证报废 + 人工裁决，浪费验证预算。

## 证据

- 冻结加载与损坏升级：core/pm_engine/verification/pipeline.py:941-975 `_load_frozen_or_escalate`（corrupt → `_escalate_env_blocked` → 人工裁决）；损坏判定的唯一来源是读端 `load_scenarios` 抛出的 ValueError（core/pm_engine/verification/scenario_gate.py:597-624 `_load_frozen_scenarios`）。
- 验收规则（navigate 必含 + 绝对 URL）：core/verify_engine/scenarios.py:937 `validate_scenario_dicts` → `_validate_web`（报「缺少 navigate 步骤」「navigate URL 必须为绝对地址」）。
- navigate 目标字段语义：目标 URL 存于步骤 `value`（core/verify_engine/scenarios.py `TestStep.value`；serving.py:578-579 注释「navigate 目标 URL 存于 value，191 个场景全部用 value 携带链接」）——迁移合成 navigate 步骤时字段必须与全链路读取一致。
- 语料实证（本仓 253 份 `.fenix/verify-progress/*/test_scenarios.json`、3224 个场景）：web 场景 192 个，其中 1 个缺 navigate 步骤（`fix-verify-contract-signal-semantics/web-inflight-toast-surfaced`）；另有 41 份冻结集过不了当前规则，成因是历史词汇/字段形态（`no_click_interception` 被当作步骤 action、cli/api 必填字段缺失等），与 navigate 规则无关——本提案的自动迁移/重出题**只覆盖契约类漂移**，其余损坏仍走人工。
- 契约漂移的历史实况（plan 阶段，非冻结复用）：.fenix/logs/fenixd.log.1 多条「场景验收未通过 … 缺少 navigate 步骤」退回 plan（2026-08-28 ~ 2026-09-08）。
- 归因更正：2026-09-18T07:29:13Z「冻结场景文件验收失败 'fix-verify-serving-disk-reclaim'」（23 条「缺少 navigate 步骤」）**不是**契约演化所致——该 spec 的 admin 处置（.fenix/admin_alerts.json）认定根因是**实现者越权向 .fenix/verify-progress 写入伪造场景证据文件**（23 条仅含 `{id,spec,status,desc}`，无 steps/kind；隔离备份见 .fenix/merge-backup/.quarantine-fix-verify-serving-disk-reclaim-1789716964/test_scenarios.json），非产品缺陷。本提案立论建立在**机制**（冻结集按当前规则验收，规则演进即 corrupt）与上述语料实证上，不依赖该事故的因果。
- 已归档 evo-add-frozen-scenario-schema-migration（spec/archive/2026-09-19-evo-add-frozen-scenario-schema-migration）：仅覆盖字段形态迁移（value→command / value→expected）+ 条目级 `schema_version` 标记，不含校验规则演化处理——本提案沿用同一「条目级版本字段 + 读端版本路由」机制。

## 设计思路

1. **冻结场景条目增加 `contract_version` 字段**（语义：「本冻结集符合哪个版本的场景验收契约规则」，字段缺失 = 1）。根节点维持 JSON 数组，不改读端契约。
2. **可机械迁移**：contract_version < 2 且为 web 场景、缺 navigate 步骤时，以引擎契约供给的被测实例 base_url（`pipeline._current_instance_base_url`，serving.py:462）合成 navigate 步骤（写入 `value`）插入首位。不挖 steps 文本：web 场景不使用 `run` 步骤（`CLI_ACTIONS = {"run"}`，`WEB_ACTIONS` 无 run，web 场景带 run 步骤本身即校验错误），steps 内通常无 URL 可挖。
3. **不可迁移**：无可用 base_url 的场景 → 移入 pending_replan，剩余场景保留执行；全部场景过时 → 删除 test_scenarios.json 并**本轮回落到出题通道**（不置 blocked 等人工）。
4. **迁移后写回**冻结文件（条目盖 contract_version=2），避免下次重复迁移；新冻结集由写端直接盖当前版本戳，下次加载零迁移。
5. **设计约束**：迁移不可重复执行；迁移 MUST 在读端验收（`load_scenarios`）**之前**对原始 dict 集执行（否则旧集先被判 corrupt、直接升级人工）；自动重出题仅适用于契约类漂移，其他损坏维持既有 blocked/env_blocked 人工通道。

## 范围

- 覆盖：基于条目级 contract_version 管理的冻结场景集（pipeline.py `_load_frozen_or_escalate` → core/verify_engine/scenarios.py `validate_scenario_dicts` 路径），且仅覆盖「v2 = web 场景 MUST 含 navigate」一类契约规则。
- 不覆盖：其他契约/词汇漂移（未知 action/断言类型、必填字段缺失等）——仍走现有 corrupt → env_blocked → 人工裁决通道。
- 不覆盖：已归档 schema_version 字段迁移（evo-add-frozen-scenario-schema-migration 已覆盖，不重复）。
- 不覆盖：非冻结场景（首轮出题不受影响，planner 已知当前契约）。
