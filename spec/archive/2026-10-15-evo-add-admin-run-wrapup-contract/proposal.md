## 背景

2026-10-05 potplayer-base 项目处置 pack2-official-encoder 验证环境阻塞时，管理员 run admin-pack2-official-encoder-1791196033 深诊断 21 组实验、环境定版执行完毕后，在写最终处置记录的瞬间被 600 轮上限击杀（exit -9）：初步处置记录已写、最终记录与修复计划未落盘，告警 109d681fbbe2 悬置 pending，spec 冻结转人工。fenixd.log 12:53:48/13:09:08 两条 turn extension 日志的 evidence 自证框架在续期决策时已知 remaining_tasks=0，仍按「60 秒内有 tool_result 流量」续满 2 次至击杀。

## 问题

1. 轮数/墙钟续期判据（core/agent_runner/runner.py `_turn_limit_action` 与 core/agent_runner/liveness.py `_supervision_deadline_action`）只看分支提交增量与尾窗工具流量，任务完成度仅观测注记；非 impl 车道无收尾预算保护。
2. administrator.md 已有「先写初步记录」「终了写最终记录」软契约，但无「诊断闭环后先落最终记录再执行长恢复动作」的次序硬规则，收尾动作集中在最后一刻。

## 方案

- 管理员提示词加硬终止契约：诊断闭环判定后先覆盖写最终处置记录，再执行环境恢复/清理；自建任务全部 completed 后禁止开新实验；最终记录不得留作最后一个动作。
- 框架在轮数上限末次扩容点与墙钟末次扩容点，对非 impl 车道且 run 内自建任务全部 completed 的 run 发一次性收尾宽限（默认 20 轮），宽限耗尽走既有击杀路径；触发判据用 run 内自建任务观测，禁用 spec tasks.md 的 remaining_tasks（数据源错位）。

## 非目标

- 不改 impl 车道既有早停/预算 sizing（evo-add-impl-run-budget-sizing、evo-add-impl-wallclock-budget-sizing 已定）。
- 不把 spec tasks.md 的 remaining_tasks 纳入任何车道续期判据（与 impl 预算 sizing 既有设计决策一致）。
- 不做击杀前「部分结果」提取。