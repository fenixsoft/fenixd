## ADDED Requirements

### Requirement: verified 终态收敛点回收在飞 verify 车道

`core/pm_engine/engine.py` 的 `_on_spec_verified` 收敛点（verification 结果采纳的统一出口，`legacy.py:497` 与 `pipeline.py:1029` 双路汇合处）MUST 新增 verify 车道自我收尾，照搬 `_stop_parallel_plan`（planner-plan 车道既有范式）：

1. 摘除在队 verify 条目：`_remove_queued_entry(spec_name, "verifier")`；
2. 终止在飞 verifier run：`cancel_run("verify-<spec_name>", reason=..., by="verify-lane")`——经既有取消原语（旗标登记 + 属主线程 terminate），车道对自己派发的 run 做生命周期收尾属该原语的本职用法；
3. 两步均须异常兜底（try/except 记 WARNING 不抛），收尾失败不得影响 verified 主流程。

语义边界：

- 回收时机是 **verified 采纳之后**（终态化起点），不改变 testing 内并发车道语义；
- 被回收 run 的结果应用侧由 `verify-late-result-terminal-guard` 能力兜底丢弃（防御纵深：即使取消未及时生效，迟到结果也不会覆写状态）；
- 不得越权终止其它 spec 或其它 agent_type 的 run。

#### Scenario: verified 时在飞 verifier run 被请求取消

- **WHEN** SPEC 处于 `testing` 且 verify 车道有一个在飞 verifier run（基础 run_id `verify-<spec>` 已登记），验证结论达成 verified
- **THEN** `_on_spec_verified` 内该 run 收到 cancel_requested，属主线程在轮询环退出；取消日志含 `by="verify-lane"` 与原因

#### Scenario: verified 时在队 verify 条目被摘除

- **WHEN** 派发队列中存在该 SPEC 的 verifier 条目，SPEC 达成 verified
- **THEN** 队列条目被摘除，daemon 不再据该条目派发新 verifier run

#### Scenario: 取消原语异常不影响 verified 主流程

- **WHEN** `cancel_run` 或队列摘除抛出异常（如 runner 未初始化、条目已被并发摘除）
- **THEN** 异常被捕获并记 WARNING，verified 流转（done → push 链）不受影响

#### Scenario: 不越权终止其它车道

- **WHEN** SPEC 达成 verified 时同项目存在其它 spec 的在飞 run 或本 SPEC 的非 verifier run（如 planner-judge 已完成归档）
- **THEN** 仅基础 run_id 匹配 `verify-<本 spec>` 的在飞 run 被取消，其余 run 不受影响
