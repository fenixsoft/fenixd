## Context

2026-10-06 核查结论（admin-pack2-official-encoder-1791196033 事件流+runner.py 现状）：
- `_turn_limit_action`（core/agent_runner/runner.py:2340-2549）活性判据=分支提交增量 ∨ 尾窗 60s tool_result 流量；remaining_tasks 只注记（2367-2383 注释明示），数据源是 spec tasks.md（runner.py:2377 → core/run_task_track.py），对 admin run 在途工作零对应。
- 扩容链：TURN_EXTENSION_STEP_FRACTION=0.25、TURN_EXTENSION_MAX=2（runner.py:373-374）+ 项目 max_turns → 400+100+100=600；击杀对应 runner.py:5644（SIGKILL 语义）。
- 墙钟侧 `_supervision_deadline_action`（core/agent_runner/liveness.py:1049-1060 附近）同型：judge 评估证据更丰富但同样只注记不判定。
- administrator.md:122/127/159 已有软契约；缺次序硬规则与新实验禁令。
- run_metrics 工具直方图已有 TaskCreate/TaskUpdate 口径，run 内自建任务观测有数据源。

## Goals / Non-Goals

- [x] admin/维护车道末次扩容收尾宽限（触发信号=run 内自建任务观测）+ 提示词硬契约
- [ ] 不动 impl 车道；不动 remaining_tasks 语义；不做击杀前部分结果提取

## Technical Design

1. runner.py：`_turn_limit_action` 末次扩容分支（extension 2/2）增加车道判定——agent_type ∈ 非 impl 车道集合（新增常量，与 runner.py:382 IMPL_LANE_AGENT_TYPES 平行）且 run 内自建任务全 completed → 发一次性收尾宽限（默认 20 轮，可配），evidence 注记 wrapup_grace；宽限耗尽走既有击杀路径。
2. liveness.py：`_supervision_deadline_action` 墙钟末次扩容同型收尾宽限，与轮数侧共用同一配置键。
3. administrator.md：硬契约三条——闭环判定后先覆盖写最终处置记录再执行长动作；自建任务全 completed 后禁止开新实验；最终记录不得留作最后一个动作。
4. 失败模式与防护：宽限触发信号误判时最坏情形与现状相同（一次性少量轮数）；与 evo-add-impl-run-budget-sizing 的 D6 早停不互相触发（车道集合不相交）。

## Open Questions

- 收尾宽限轮数缺省值（20）是否按车道区分（admin 与 dispute-judge）——实现时按观测调参。