# Requirement: 冻结场景验收契约版本化自动迁移

## Requirement 1: 契约版本字段

冻结场景文件 MUST 包含 `contract_version` 整型字段，标识该冻结集所符合的场景验收契约规则版本。系统加载冻结集时 MUST 读取此字段并路由迁移逻辑。

### Scenario: 首次契约升级自动迁移

- **GIVEN** 冻结场景文件 contract_version=1（< 当前版本 2）、场景集中含 web 场景（steps 中有 URL 打开命令）缺 navigate 步骤
- **WHEN** 系统加载该冻结集（_load_frozen_or_escalate 路径）
- **THEN** 系统 MUST 对可定位 URL 的场景自动补齐 navigate 步骤（url 取自 command 中 http(s) 链接），并将 contract_version 升至 2 后写回冻结文件；不可定位 URL 的场景移入 pending_replan 列表

### Scenario: contract_version 已匹配

- **GIVEN** 冻结场景文件 contract_version=2（= 当前版本）
- **WHEN** 系统加载该冻结集
- **THEN** 不触发迁移，直接进入场景验收（validate_scenario_dicts）

## Requirement 2: 全场景过时自动重新出题

若迁移后 pending_replan 场景数 = 冻结集场景总数（全部过时无法机械迁移）或迁移后无合法场景，系统 MUST 走重新出题通道：删除 test_scenarios.json（触发 planner 重新生成当前契约版本的场景集），MUST NOT 置 blocked/env_blocked 待人工裁决。

### Scenario: 部分迁移成功

- **GIVEN** 迁移后有若干场景成功补齐 navigate（contract_version 已升至 2），另有部分场景无法迁移
- **WHEN** 迁移函数返回 pending_replan 列表（非空且非全量）
- **THEN** 被移除场景不再参与本轮验证；剩余场景继续冻结执行（schema_version + contract_version 已更新）

### Scenario: 全部过时自动重新出题

- **GIVEN** 迁移后所有场景均无法定位 URL、全部移入 pending_replan
- **WHEN** 迁移函数返回 aborted='all_scenarios_stale'
- **THEN** pipeline 走 replan 通道：删除冻结文件后由 planner 重新出题（新场景集 contract_version=2），MUST NOT 经人工裁决；INFO 日志记录「契约升级全场景过时、已自动重新出题」

## Requirement 3: 迁移日志与审计

每次契约迁移 MUST 写 INFO 日志：场景总数、成功迁移数（补齐 navigate）、移除过时数、contract_version 变更。迁移失败（不可恢复错误）MUST 写 WARNING 日志并附 pending_replan 场景 id 列表，由现有异常通道上报。

## Requirement 4: 多版本迁移链兼容

若未来 contract_version 继续升级（v3、v4…），系统 MUST 支持从 v1 直接迁移到 v3（跳版本迁移），通过 while contract_version < CURRENT_VERSION 循环执行各版本迁移逻辑。每个版本的迁移逻辑为独立函数，由版本号索引。