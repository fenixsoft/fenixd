## Context

2026-10-06 核查结论（admin-pack2-official-encoder-1791196033 事件流+runner.py 现状）：
- `_turn_limit_action`（core/agent_runner/runner.py:2340-2549）活性判据=分支提交增量 ∨ 尾窗 60s tool_result 流量；remaining_tasks 只注记（2367-2383 注释明示），数据源是 spec tasks.md（runner.py:2377 → core/run_task_track.py），对 admin run 在途工作零对应。
- 扩容链：TURN_EXTENSION_STEP_FRACTION=0.25、TURN_EXTENSION_MAX=2（runner.py:377-378）+ 项目 max_turns 按比例扩容；事件时按 400+100+100=600 击杀（proposal 记录口径），现 .fenix/config.yaml agents.max_turns=800（同式封顶 1200）——机制按配置取值，不依赖具体数字；击杀对应 runner.py:5644（SIGKILL 语义）。
- 墙钟侧 `_supervision_deadline_action`（core/agent_runner/liveness.py:1268 起，max_extensions 封顶分支在其内）同型：judge 评估证据更丰富但同样只注记不判定。
- administrator.md:122/127/159 已有软契约；缺次序硬规则与新实验禁令。
- run 内自建任务完成态观测数据源=core/run_task_track.py 的 run 产物 TaskCreate/TaskUpdate 解析（completed_idx / last_update_status，单点解析循环）；run_metrics 直方图只有整 run 累计调用计数、无状态粒度，仅可作旁证，不能判定「全部 completed」。

## Goals / Non-Goals

- [x] admin/维护车道末次扩容收尾宽限（触发信号=run 内自建任务观测）+ 提示词硬契约
- [ ] 不动 impl 车道；不动 remaining_tasks 语义；不做击杀前部分结果提取

## Technical Design

1. runner.py：`_turn_limit_action` 扩容封顶分支（`turn_extensions_used >= TURN_EXTENSION_MAX` 的现无条件 kill 处，runner.py:2431）增加车道判定——agent_type ∈ 非 impl 车道集合（新增常量，与 runner.py:386 IMPL_LANE_AGENT_TYPES 平行）且 run 内自建任务全 completed（判据数据源=run_task_track run 产物解析；清单为空即 run 无 TaskCreate 记录时不触发，维持既有击杀）→ 发一次性收尾宽限（默认 20 轮，可配；已发放标记落 _turn_branch_state 防重复），evidence 注记 wrapup_grace；宽限耗尽走既有击杀路径。
2. liveness.py：`_supervision_deadline_action` 墙钟扩容封顶分支（max_extensions 用满处）同型收尾宽限，一次性发放量按秒折算（宽限轮数 × 该 run 近期平均每轮墙钟，折算口径实现时定），与轮数侧共用同一配置开关键与「是否已发放」状态。
3. administrator.md：硬契约三条——闭环判定后先覆盖写最终处置记录再执行长动作；自建任务全 completed 后禁止开新实验；最终记录不得留作最后一个动作。
4. 失败模式与防护：宽限触发信号误判时最坏情形与现状相同（一次性少量轮数）；与 evo-add-impl-run-budget-sizing 的 D6 早停不互相触发（车道集合不相交）；宽限发放/耗尽的 reason 文案 MUST NOT 改动既有豁免匹配子串（"extension budget exhausted" 等——budget._is_exemptable_reason 按 reason 子串匹配，liveness.py:1311 注释明示），观测信息只进 evidence 不进 reason，沿用 _annotated 既有口径。

## Open Questions

- 收尾宽限轮数缺省值（20）是否按车道区分（admin 与 dispute-judge）——实现时按观测调参。