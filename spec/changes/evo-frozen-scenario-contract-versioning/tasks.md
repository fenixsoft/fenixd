## Deliverables

```yaml
- path: core/pm_engine/verification/pipeline.py
  kind: modify
- path: core/pm_engine/verification/scenario_gate.py
  kind: modify
- path: tests/test_frozen_contract_evolution.py
  kind: new
```

## 1. 契约版本常量与读取

- [ ] 1.1 core/pm_engine/verification/scenario_gate.py：定义 CURRENT_CONTRACT_VERSION = 2 常量（含义：v2 含 web 场景 MUST 含 navigate 步骤）
- [ ] 1.2 core/pm_engine/verification/pipeline.py _load_frozen_or_escalate 路径：读取冻结文件根对象 contract_version 字段（缺省值 1，兼容旧冻结文件）
- [ ] 1.3 路由条件：contract_version < CURRENT_CONTRACT_VERSION 时进入迁移逻辑；否则跳过

## 2. 契约升级迁移函数

- [ ] 2.1 core/pm_engine/verification/scenario_gate.py：新增 migrate_frozen_contract(scenarios, current_version) 函数，返回 (migrated_scenarios, pending_replan_ids)
- [ ] 2.2 v1→v2 迁移：对每个场景，steps 中含 action=run 且 command 含 http(s) URL 但无 action=navigate → 提取 URL 插入 navigate 步骤首位、标记 schema_version=2；无明确 URL 且无 base_url → 移入 pending_replan_ids
- [ ] 2.3 空集兜底：若所有场景移入 pending_replan（migrated_scenarios 为空），函数返回 aborted='all_scenarios_stale'

## 3. 迁移集成与重新出题通道

- [ ] 3.1 core/pm_engine/verification/pipeline.py：_load_frozen_or_escalate 中，contract_version < 当前版本时调用 migrate_frozen_contract；成功后写回冻结文件（scenarios 已更新、contract_version 已升至 2）
- [ ] 3.2 迁移结果为 aborted → 不置 blocked/env_blocked，走现有 replan 通道（delete test_scenarios.json 触发出题），INFO 日志说明全场景过时与旧 contract_version
- [ ] 3.3 部分迁移（pending_replan 非空非全量）→ 被移除场景不参与本轮，剩余场景继续执行；WARNING 日志列出 pending_replan 场景 id
- [ ] 3.4 迁移幂等保障：contract_version >= CURRENT_CONTRACT_VERSION 时零操作（不重复迁移）

## 4. 测试

- [ ] 4.1 tests/test_frozen_contract_evolution.py：覆盖以下场景：
  - (a) contract_version=1 冻结集含可定位 URL 的 web 场景 → 迁移后 navigate 已补齐、contract_version=2、场景通过 validate_scenario_dicts
  - (b) contract_version=1 含无法定位 URL 场景 → 该场景移入 pending_replan，剩余场景正常
  - (c) 全场景过时（pending_replan = 全量）→ 返回 aborted='all_scenarios_stale'
  - (d) contract_version=2 冻结集 → 直通过版本检查、不触发迁移
  - (e) 迁移后冻结文件 contract_version 字段已更新写回持久化