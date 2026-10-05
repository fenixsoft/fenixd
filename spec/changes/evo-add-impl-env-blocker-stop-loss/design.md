## Context

2026-10-06 核查结论（impl-…-1791177321-a1 事件流+runner.py+config 现状）：
- remaining_tasks 口径：runner.py:2377-2383 读主树 tasks.md，worktree run 期间恒静态，不能作停滞判据。
- run 流内任务完成已有单点解析：core/run_task_track.py（流内 TaskUpdate 观测）。
- 相邻机制边界：kill_early（`_turn_kill_early_evidence`，runner.py:2551-2609，缺省关闭、仅 impl 车道、方向为 remaining_tasks ≥阈值且零进度才杀）；latency 停滞预算（evo-add-run-stop-loss，缺省关闭、未配置）。
- design.md fallback 条款先例：pack2-official-encoder design.md:38「相机桥不可用→收口场景如实标注失败原因并回退主机端核验+真机人工兜底」。
- 配置键先例：core/config.py:297-330 agents.run_stall_budget_* 风格。

## Goals / Non-Goals

- [x] 提示词止损硬规则 + 进度停滞观测面（WARNING 注记，不改判定）
- [ ] 不动预算轴（evo-add-impl-run-budget-sizing / evo-add-impl-wallclock-budget-sizing）；不自动击杀

## Technical Design

1. agents/implementer.md「约束」段追加止损规则（见 spec.md），并要求优先消费 design 的 fallback 条款。
2. agents/planner-plan.md：环境依赖类任务在任务书标注「环境依赖、有/无 fallback」类别，供止损规则联动。
3. core/agent_runner/runner.py：轮询路径加「自最近 TaskUpdate completed 起的轮数」计数（复用 run_task_track 流内解析），超阈（配置键沿 agents.run_stall_budget_* 先例归一化）打 WARNING + turn_extension/timeout evidence 注记。
4. 与 kill_early / latency 停滞预算的边界：本观测只注记不判定，不与之互相触发。

## Open Questions

- 阈值缺省 200 轮的标定：本案击杀前 275 轮零完成，200 可提前约 11 分钟预警；实现后按观测调参。