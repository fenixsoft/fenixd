# Requirement: 冻结场景验收契约版本化自动迁移

## Requirement 1: 契约版本字段

冻结场景文件（test_scenarios.json，根节点为 JSON 数组）中的场景条目 MUST 支持 `contract_version` 整型字段，标识该条目所符合的场景验收契约规则版本；缺失或非整型 MUST 视为 1（存量兼容）。系统加载冻结集时 MUST 读取此字段并路由迁移逻辑。写盘路径（`prepare_scenarios_for_write`）MUST 恒定写入当前 `contract_version`，使新产出冻结集天然为当前契约版本。

### Scenario: 首次契约升级自动迁移

- **GIVEN** 冻结场景条目 `contract_version=1`（< 当前版本 2），其中含 web 场景且缺 navigate 步骤，且引擎可供给被测实例 `base_url`
- **WHEN** 系统加载该冻结集（`_load_frozen_or_escalate` 路径）
- **THEN** 系统 MUST 在**读端验收（`load_scenarios`）之前**完成迁移：以 `base_url` 合成 navigate 步骤（URL 写入步骤 `value` 字段，与全链路读取口径一致）插入 steps 首位，条目 `contract_version` 升至 2 并写回冻结文件；无法获得 URL 的 web 场景 MUST 移入 pending_replan 列表并从本轮集合剔除

### Scenario: contract_version 已匹配

- **GIVEN** 冻结场景条目 `contract_version=2`（= 当前版本）
- **WHEN** 系统加载该冻结集
- **THEN** 不触发迁移、不写回、不备份，直接进入场景验收（`validate_scenario_dicts`）

## Requirement 2: 全场景过时自动重新出题

若迁移后无任何合法场景（全部场景缺 navigate 且无可用 URL，`aborted='all_scenarios_stale'`），系统 MUST 走重新出题通道：删除 test_scenarios.json（触发下轮/本轮 planner 生成当前契约版本的场景集），MUST NOT 置 blocked/env_blocked 待人工裁决；本轮 MUST 回落到既有出题分支执行，MUST NOT 递归调用验证流水线。除本项外的其他加载失败（JSON 语法错误、非契约类规则不匹配、无迁移路径 `aborted='no_migration_path'`）MUST 维持既有 corrupt → env_blocked 人工通道。

### Scenario: 部分迁移成功

- **GIVEN** 迁移后有若干 web 场景成功补齐 navigate（`contract_version` 已升至 2），另有部分场景无法定位 URL
- **WHEN** 迁移函数返回 `pending_replan` 列表（非空且非全量）
- **THEN** 被剔除场景不再参与本轮验证（WARNING 记录 id 列表）；剩余场景继续冻结执行（版本戳已更新）

### Scenario: 全部过时自动重新出题

- **GIVEN** 迁移后所有场景均无法定位 URL、全部移入 `pending_replan`，或冻结集为空
- **WHEN** 迁移函数返回 `aborted='all_scenarios_stale'`
- **THEN** pipeline MUST 删除冻结文件并返回「无冻结」信号使本轮进入既有出题分支，MUST NOT 经人工裁决；INFO 日志记录「契约升级全场景过时、已自动重新出题（旧场景数/旧 contract_version）」

## Requirement 3: 迁移日志与审计

每次契约迁移 MUST 写 INFO 日志：场景总数、成功迁移数（补齐 navigate）、移除过时数、contract_version 变更（1→2）。被移除的 pending_replan 场景 MUST 写 WARNING 并附场景 id 列表。迁移无法完成（未登记版本段/写回失败/MUST NOT 迁移后仍验收失败）时 MUST 留痕（ERROR/WARNING）并交由既有异常通道上报，MUST NOT 静默吞掉。

## Requirement 4: 多版本迁移链兼容

系统 MUST 支持从任意旧版本直接迁移到当前版本（跳版本迁移），以版本号登记表 + `while contract_version < CURRENT_CONTRACT_VERSION` 循环逐段推进；每个版本的迁移逻辑为独立函数。未登记版本段或无可用迁移路径时 MUST fail-closed（返回 `aborted='no_migration_path'` 并回退既有 corrupt → env_blocked 人工通道），MUST NOT 猜测或跳过版本。
