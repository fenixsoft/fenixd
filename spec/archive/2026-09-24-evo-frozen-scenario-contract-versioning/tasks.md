## Deliverables

```yaml
- path: core/verify_engine/scenarios.py
  kind: modify
- path: core/pm_engine/verification/pipeline.py
  kind: modify
- path: tests/test_frozen_contract_evolution.py
  kind: new
```

> 说明：`migrate_frozen_contract` 与常量落在 core/verify_engine/scenarios.py（场景模型/词表唯一权威源，引擎层不得 import pm_engine）；pipeline.py 只负责读文件、注入 base_url、写回与路由。scenario_gate.py 的 `_load_frozen_scenarios` 若被改动，按“改 pipeline 调用点”同等对待（当前设计不必改它）。

## 1. 契约版本常量与条目字段

- [x] 1.1 core/verify_engine/scenarios.py：定义 `CURRENT_CONTRACT_VERSION = 2`、`CONTRACT_VERSION_FIELD = "contract_version"` 常量，并加注释说明「v2 = web 场景 MUST 含 navigate 步骤（绝对 URL）」及「字段缺失/非整型视为 1」
- [x] 1.2 core/verify_engine/scenarios.py：`prepare_scenarios_for_write` 恒定盖 `contract_version = CURRENT_CONTRACT_VERSION` 戳（与既有 `schema_version` 盖戳同处），保证新写盘冻结集天然为当前契约版本
- [x] 1.3 core/pm_engine/verification/pipeline.py `_load_frozen_or_escalate`：读冻结文件**原始 JSON 数组**（不再先走 `_load_frozen_scenarios` 验收），取集内 `contract_version` 最小值（缺失/非整型=1）作为路由判据

## 2. 契约迁移函数（core/verify_engine/scenarios.py）

- [x] 2.1 新增 `migrate_frozen_contract(scenarios, current_version=CURRENT_CONTRACT_VERSION, base_url="") -> dict`，返回 `{'migrated': list, 'pending_replan': list, 'aborted': str}`；纯函数、不读写盘、不 import pm_engine
- [x] 2.2 版本登记表 `_CONTRACT_MIGRATIONS = {2: _migrate_contract_to_v2}` + `while current < CURRENT_CONTRACT_VERSION` 循环（支持跳版本迁移）；未登记版本段 → `aborted='no_migration_path'`
- [x] 2.3 v1→v2 迁移分支：
  - 非 web 场景 → 原样保留 + 盖 `contract_version=2`
  - web 场景已有 navigate → 只盖戳、步骤零变化
  - web 场景缺 navigate → 候选 URL 顺序：场景内 step 的 `url` 字段（`^https?://\S+$`）> 入参 `base_url`；命中则合成 `{"action": "navigate", "value": <url>, "description": "契约 v2 自动补齐（navigate 绝对 URL）"}` 插入 steps 首位 + 盖戳；未命中 → 场景 id 进 `pending_replan` 并从结果剔除
  - MUST NOT 从 steps 文本正则挖 URL（web 场景无 run 步骤；navigate 目标字段为 `value`，见 serving.py:578-579）
- [x] 2.4 空集/全过时：迁移后 `migrated` 为空 → `aborted='all_scenarios_stale'`；场景集为空（无待迁移项）亦同语义

## 3. 迁移集成与重新出题通道（core/pm_engine/verification/pipeline.py）

- [x] 3.1 `_load_frozen_or_escalate` 顺序改造（关键约束）：读原始 JSON → 版本路由 → 需要迁移时取 `base_url = self._current_instance_base_url(spec_name)` 调迁移 → 写回 → 最后才 `load_scenarios` 验收；迁移 MUST 先于验收执行（否则旧集先被判 corrupt 直接升级人工）
- [x] 3.2 迁移前备份原文件为 `<verify_dir>/test_scenarios.json.contract-v1.bak`；写回失败 ERROR 留痕并照常以内存迁移结果继续（不退回 corrupt）
- [x] 3.3 迁移后写回冻结文件（数组形态 + 条目盖 `schema_version`/`contract_version` 戳）；迁移结果回注 `self._frozen_migrated` 供阶段1 复用分支 diff 基线使用
- [x] 3.4 `aborted='all_scenarios_stale'` 或 `'no_migration_path'` 差异处置：前者删 `test_scenarios.json` 并返回 `(None, False)` **本轮回落到既有出题分支**（不置 blocked/env_blocked、不递归调用 `_run_three_stage_verification`）；后者维持既有 corrupt → env_blocked（fail-closed）
- [x] 3.5 部分迁移（`pending_replan` 非空非全量）→ 被剔除场景不参与本轮，剩余场景继续；WARNING 列出待重排场景 id
- [x] 3.6 迁移后验收仍失败 → 既有 corrupt → env_blocked，并在处置选项文本补第③条回退指引（删除/恢复 `test_scenarios.json.contract-v1.bak`）
- [x] 3.7 幂等：`contract_version >= CURRENT_CONTRACT_VERSION` → 零操作（不迁移、不写回、不备份）
- [x] 3.8 日志（spec R3）：迁移成功 INFO（场景总数/成功迁移数/移除过时数/contract_version 变更），移除项 WARNING 附 id 列表

## 4. 测试

- [x] 4.1 tests/test_frozen_contract_evolution.py：纯函数级（无需 verify server）
  - (a) v1 web 缺 navigate + base_url → navigate 步骤以 **`value`** 承载 URL、插首位、`contract_version=2`、结果过 `validate_scenario_dicts`
  - (b) web 场景 steps 含 run+URL 但无 navigate → 不挖文本，改用 base_url
  - (c) base_url 空且无 url 字段 → 该场景进 `pending_replan`，其余照常
  - (d) 全量 `pending_replan` → `aborted='all_scenarios_stale'`、`migrated` 为空
  - (e) 已有 navigate 的 web / cli / api 场景 → 只盖戳、步骤零变化
  - (f) 幂等：v2 集合 → 零操作
  - (g) 跳版本（CURRENT_CONTRACT_VERSION=3 桩）：v1 走两段迁移；未登记版本段 → `aborted='no_migration_path'`
- [x] 4.2 pipeline 调用点级（mock 冻结文件 + patch `_current_instance_base_url` / 写回路径）
  - (h) v1 冻结文件 → 迁移 + 写回后 `contract_version=2` 持久化、`.contract-v1.bak` 存在
  - (i) 全过时 → 返回 `(None, False)`、冻结文件被删除、**未调用 `_escalate_env_blocked`**、本轮进入出题分支
  - (j) 写端回归：`prepare_scenarios_for_write` 输出含 `contract_version=CURRENT_CONTRACT_VERSION`
