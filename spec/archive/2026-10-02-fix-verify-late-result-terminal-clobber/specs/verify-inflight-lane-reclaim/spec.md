## ADDED Requirements

### Requirement: verified 终态收敛点回收在飞 verify 车道

`core/pm_engine/engine.py` 的 `_on_spec_verified` 收敛点（verification 结果采纳的统一出口，`legacy.py:497` 与 `pipeline.py:1029` 双路汇合处）MUST 新增 verify 车道自我收尾，照搬 `_stop_parallel_plan`（planner-plan 车道既有范式）：

1. 摘除在队 verify 条目：`_remove_queued_entry(spec_name, "verifier")`；
2. 终止在飞 verifier run：经既有取消原语 `cancel_run`（旗标登记 + 属主线程 terminate）——车道对自己派发的 run 做生命周期收尾属该原语的本职用法（`_stop_parallel_planning` 范式既有解读：调用方限制指旁链不得越权终止他人 run）。取消键 MUST 为在飞 run 的**完整 run 级 id（含 epoch，如 `verify-<spec>-<epoch>`）**，且仅对归属复核（`run_spec_part(aid) == spec_name`）通过的 run 调用；MUST NOT 传裸 `verify-<spec_name>`——旗标登记键经 `_normalize_run_id` 归一后与消费点（attempt 循环/轮询环以带 epoch 的 run 级 id 归一判定）不收敛，取消静默失效且返回值仍显 `cancel_requested`；
3. 两步均须异常兜底（try/except 记 WARNING 不抛），收尾失败不得影响 verified 主流程。

语义边界：

- 回收时机是 **verified 采纳之后**（终态化起点），不改变 testing 内并发车道语义；
- 回收执行点 = `_on_spec_verified` 内 verified→done 转移成功之后（与 `_evict_spec_serving` 终局驱逐同点）；D7 逃生门（验证进度不完整回退 testing 断点续跑）与「blocker 保持 verified」路径 MUST NOT 回收——门禁要求续跑的在飞车道不得被拆；
- 取消旗标按完整 run id（含 epoch）登记，天然不波及门禁回退后重派的新 epoch verify run 与人工重验 run；
- 被回收 run 的结果应用侧由 `verify-late-result-terminal-guard` 能力兜底丢弃（防御纵深：即使取消未及时生效，迟到结果也不会覆写状态）；
- 不得越权终止其它 spec（含同根后代 spec，以 `run_spec_part` 归属复核为准）或其它 agent_type 的 run。

#### Scenario: verified 时在飞 verifier run 被请求取消

- **WHEN** SPEC 处于 `testing` 且 verify 车道有一个在飞 verifier run（run 级 id `verify-<spec>-<epoch>` 已登记），验证结论达成 verified 并推进 done
- **THEN** 该 run 的取消旗标被登记且登记键与其归一 run id 收敛（属主轮询环视角 `_cancel_is_requested(<在飞 run id>)` 为真，非仅 `cancel_run` 返回 `cancel_requested`），属主线程在轮询环退出；取消日志含 `by="verify-lane"` 与原因

#### Scenario: verified 时在队 verify 条目被摘除

- **WHEN** 派发队列中存在该 SPEC 的 verifier 条目，SPEC 达成 verified
- **THEN** 队列条目被摘除，daemon 不再据该条目派发新 verifier run

#### Scenario: 取消原语异常不影响 verified 主流程

- **WHEN** `cancel_run` 或队列摘除抛出异常（如 runner 未初始化、条目已被并发摘除）
- **THEN** 异常被捕获并记 WARNING，verified 流转（done → push 链）不受影响

#### Scenario: 不越权终止其它车道

- **WHEN** SPEC 达成 verified 时同项目存在其它 spec 的在飞 run（含同根后代 spec，其 run id 形如 `verify-<本spec>-x-<epoch>` 虽前缀相似但归属其它 spec）或本 SPEC 的非 verifier run（如 planner-judge 已完成归档）
- **THEN** 仅 `run_spec_part` 归属解析为本 spec 的在飞 run 被取消，其余 run 不受影响

#### Scenario: 验证进度不完整回退续跑时不回收车道

- **WHEN** SPEC 达成 verified 但验证完成度闸门判定进度不完整，D7 逃生门把 SPEC 回退 testing 断点续跑（不推进 done）
- **THEN** 不执行 verify 车道收尾：在飞 verifier run 不被取消、在队条目不被摘除，续跑/重派验证不受残留取消旗标影响
