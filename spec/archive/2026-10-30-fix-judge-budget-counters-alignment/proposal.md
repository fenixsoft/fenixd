## Why

add-command-center 监视期实证（2026-10-27）：judge 场景原地修复预算（3 轮/episode）17:52 耗尽并排程重验，但重启后的排程重验 episode 中 judge 第 4 轮**照样原地修复 8 个场景并申报 scenario-repaired**——修复预算按 episode 重置、重跑硬上限（6/5）按生命周期累计，同一循环被两套互不知情的预算管着：修复机制自认预算内，冻结却由另一个计数触发，人工面对的告警（「重跑超上限」）完全看不出真实耗尽来源与修复历史。

## What Changes

- 修复预算耗尽后的排程重验 episode 内，judge MUST 以**无修复纯归因模式**运行：允许定性 product-bug / test-defect（仅记录，不改写场景文件）/ env，MUST NOT 改写场景文件、MUST NOT 申报 scenario-repaired——「不再重入」承诺真正兑现
- judge_rerun_cap 硬上限冻结的告警与裁决上下文 MUST 附「场景修复预算状态」（当前累计修复轮数、是否已耗尽、历次修复申报摘要），人工可判断真实耗尽来源
- 重跑硬上限保持生命周期累计语义（清零点 = verified 落定 + 人工解冻，由 fix-unfreeze-judge-counter-reset 补齐），不在本 SPEC 改动

## Capabilities

### New Capabilities
- `judge-repair-budget-alignment`: 场景修复预算与重跑硬上限双计数口径统一——预算耗尽后修复通道持久关闭，人工裁决上下文完整

### Modified Capabilities

## Impact

- `core/pm_engine/verification/pipeline.py`：judge 修复通道门（scenario-repaired 申报受理处——修复预算耗尽状态拒绝改写）
- `core/state_machine.py`：修复申报计数留痕字段单点定义（预算口径，与 `_judge_rerun_count` 同族清零点）
- `core/pm_engine/verification/escalation.py`：无行为改动（门直读 STATE 持久字段、无状态传递，见 design D2/D3；`_escalate_scenario_repair_exhausted` 仅属任务 2.1 写点审计范围）
- `core/pm_engine/verification/judge_gate.py`：`_judge_hard_cap_freeze` 告警上下文补修复预算摘要
- 新增 `tests/test_judge_repair_budget_alignment.py`；既有 judge 预算相关用例回归
