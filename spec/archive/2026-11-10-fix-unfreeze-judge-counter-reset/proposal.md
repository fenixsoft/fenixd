## Why

add-command-center 监视期实证（2026-10-27 19:17）：judge 重跑超上限（6/5 轮）冻结后人工解冻，管道 3 分钟跑完 stage2 即再次触发 `count(6) > 5` **原样再冻**——`unfreeze_spec` 的清零集漏了 `_judge_rerun_count` 与 `_judge_cap_frozen` 两个字段，而 `state_machine.py:635-639` 的注释明确声称「唯一清零点 = 验证通过**与人工 unfreeze_spec**」。文档与实现脱节，人工裁决出口对 judge_rerun_cap 冻结类形同虚设（人工必须解冻后立刻手动补清计数才能推进）。

## What Changes

- `unfreeze_spec` 清零集补入 `_judge_rerun_count = 0` 与 `_judge_cap_frozen = False`（与既有验证计数同一原子写）；`cap_frozen` 不清会导致计数恒冻结在 0、judge 预算彻底失效，两字段 MUST 成对清除
- 同步修正 `state_machine.py:635-639` 注释与实现的一致性（实现补齐后注释即成立，核对表述即可）

## Capabilities

### New Capabilities
- `unfreeze-judge-counter-reset`: 人工解冻随同一原子写清零 judge 重跑计数与硬上限冻结旗标，judge_rerun_cap 冻结的人工裁决出口可达

### Modified Capabilities

## Impact

- `core/state_machine.py`：`unfreeze_spec` 清零集（既有 `SCENARIO_REPAIR_EXHAUSTED_FIELD`/`LEGACY_DEGRADE_STREAK_FIELD` 等同段）
- `tests/test_unfreeze_judge_counter_reset.py`（新建）：解冻清零与再冻路径回归
- 消费端 `core/pm_engine/verification/judge_gate.py` 零改动（其读侧语义不变）
