## Why

2026-10-26 add-command-center 冻结事故：verify agent 把冻结场景文件 `test_scenarios.json` 写成 dict 包裹形态（顶层 `{"spec","total","scenarios"}`），冻结装载读端对顶层非数组 fail-closed，直接触发「场景计划争议」→ 连续 2 轮自动冻结转人工，39 分钟真实验证成果作废。dict 包裹的机械拯救 `_salvage_top_level_dict` 已存在（evo-scenario-product-toplevel-contract 2.2 交付），但只挂在阶段 2 验收归因点，冻结装载读端未接线——同一形态在两条读端上一救一炸。

## What Changes

- 冻结场景装载读端（`core/pm_engine/verification/pipeline.py` 冻结装载段）在顶层非数组检查前接入既有 `_salvage_top_level_dict` 拯救：顶层为「dict 且含 scenarios 数组」→ 解包重验 → 以纯数组原子重写落地 → 按解包结果继续既有契约迁移与装载
- 解包不可拯救（无 scenarios 键 / 解包后条目仍非法 / 落地写失败）→ 维持既有 corrupt → env_blocked 人工通道，行为不变
- 纯数组顶层 → 行为逐位不变

## Capabilities

### New Capabilities
- `frozen-scenario-salvage`: 冻结场景文件顶层 dict 包裹的机械拯救——冻结装载读端对 dict 包裹形态先解包止损再装载，不可拯救才转人工

### Modified Capabilities

## Impact

- `core/pm_engine/verification/pipeline.py`：冻结装载段（顶层形态检查分支）单点接线
- `tests/test_frozen_scenario_schema_migration.py`：冻结装载契约测试扩展（四场景）
- 不改变阶段 2 验收归因点的既有拯救路径；不改变 corrupt → env_blocked 人工通道语义
