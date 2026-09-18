# Proposal: frozen-scenario-contract-versioning

## 问题

场景验收契约升级（新增校验规则，如「web 场景必须含 navigate（绝对 URL 打开）步骤」）后，已冻结的存量场景集因生成于旧契约之下，批量不通过新规则验收 → 整体被判 corrupt（冻结场景文件损坏/验收失败），spec 置 blocked 待人工裁决「删除冻结文件批准重新出题」或「手动修复」。每次契约演化均触发整轮验证报废 + 人工裁决，浪费验证预算。

## 证据

- 2026-09-18T07:29:13Z「冻结场景文件验收失败 'fix-verify-serving-disk-reclaim'」——23 个 web 场景缺 navigate 步骤，整轮报废、blocked 约 26 分钟、2 次 admin 唤起
- 冻结加载机制：core/pm_engine/verification/pipeline.py:941 _load_frozen_or_escalate（corrupt → env_blocked → 人工裁决）
- 场景验收（navigate 必含判定）：core/pm_engine/verification/scenario_gate.py validate_scenario_dicts
- 已归档 evo-add-frozen-scenario-schema-migration（spec/archive/2026-09-19-evo-add-frozen-scenario-schema-migration）：仅覆盖字段形态迁移（value→command/value→expected）+ schema_version 标记，不含校验规则演化处理

## 设计思路

1. **冻结场景文件增加 `contract_version` 字段**（语义：「本冻结集符合哪个版本的场景验收契约规则」）。契约版本升级时（如从 v1 升到 v2：v2=MUST 含 navigate），系统对 `contract_version < 2` 的冻结集做自动迁移。
2. **可机械迁移**：对 schema_version >= 2 但 contract_version < 2 的 web 场景（steps 中有 URL 打开命令但无 navigate），自动补齐 navigate 步骤（从 command 中提取 URL）。
3. **不可迁移**：无法从 steps 中提取明确 URL 的场景 → 移入 pending_replan 列表，剩余场景保留执行；若全部场景过时（pending_replan = 全量） → 走现有重新出题通道（删除 test_scenarios.json 触发 planner 重新生成，不置 blocked 等人工）。
4. **迁移后写回**冻结文件（contract_version 升至 2），避免下次重复迁移。
5. **设计约束**：迁移通道 MUST NOT 对 schema_version 已匹配当前版本的冻结集重复迁移；所有迁移 MUST 在 _load_frozen_or_escalate 路径、场景验收前执行。

## 范围

- 覆盖所有基于 schema_version 管理的冻结场景文件（pipeline.py: _load_frozen_or_escalate → scenario_gate.validate_scenario_dicts 路径）
- 不覆盖：已归档 schema_version 字段迁移（evo-add-frozen-scenario-schema-migration 已覆盖，不重复）
- 不覆盖：非冻结场景（首轮出题不受影响，planner 已知当前契约）