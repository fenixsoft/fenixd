# Design: fix-unfreeze-judge-counter-reset

## Context

judge 重跑硬上限链路：`core/pm_engine/verification/judge_gate.py:632` `_judge_rerun_count(pipeline, spec, delta)` 读写 STATE 条目字段；`:436-439` 派发门 `delta=1` 后 `count > _MAX_JUDGE_RERUNS(5)` 即 `_judge_hard_cap_freeze`（置 `_judge_cap_frozen=True`）。`_judge_cap_frozen` 的作用是**停递增**（`:644` frozen 标记时强制不再递增），**不挡冻结判定**——`count=6` 恒大于 5，故解冻后首次 judge 派发必然原样再冻（10-27 19:17 实证：解冻→管道 3 分钟跑完 stage2→judge 门再冻）。

`state_machine.py:635-639` 注释声称 `_judge_rerun_count`「唯一清零点 = 验证通过与人工 unfreeze_spec」，但 `unfreeze_spec` 清零集（updates dict，state_machine.py:2415-2441 附近，含 `SCENARIO_REPAIR_EXHAUSTED_FIELD`/`LEGACY_DEGRADE_STREAK_FIELD` 等）未含这两个字段——注释与实现脱节。

## Goals / Non-Goals

**Goals:**
- 解冻后 judge 预算从零重获，judge_rerun_cap 冻结的人工出口可达
- 与既有验证计数清零同一原子写，无半途态

**Non-Goals:**
- 不改 judge_gate 派发门与 `_judge_hard_cap_freeze` 本体语义
- 不改 `_MAX_JUDGE_RERUNS` 上限值
- 不动 reset_verification 既有清零清单（其本就含 judge 重跑计数，与解冻双出口并存）

## Decisions

- **D1 清零集补两字段**：`updates["_judge_rerun_count"] = 0` 与 `updates["_judge_cap_frozen"] = False` 加在既有 `SCENARIO_REPAIR_EXHAUSTED_FIELD = 0` 同段。字段名以 judge_gate.py `_judge_rerun_count` 实现内读写的键为准（若已有命名常量则复用；若无，在 state_machine 字段名单点定义常量供两处引用，避免裸串漂移——对齐 :628-633 既有「字段名单点定义」范式）。
- **D2 成对清除的理由**：只清计数不清 `cap_frozen`，旗标残留使递增恒失效 → 计数恒 0，judge 硬上限从此对生命周期失明；只清旗标不清计数则 `6 > 5` 立即再冻。MUST 成对。
- **D3 注释核对**：:635-639 注释在实现补齐后即自洽，任务中核对一次表述（「与人工 unfreeze_spec」），不改写语义。

## Risks / Trade-offs

- **毒 spec 无限循环敞口？** 该顾虑对「admin 处置复位清零」成立（故注释明确 admin 复位不清），但人工解冻是唯一人工裁决出口且需人持凭据操作，与 `_env_block_rounds` 既有「解冻清零」同口径，风险等价已被框架接受。
- **解冻即重获全部 5 轮预算**：judge 轮次本身有 verdict 稳定性复用与轮内停派两级节流，重复浪费由既有机制吸收，不再叠加生命周期上限拦截人工出口。
