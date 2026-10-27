# Design: fix-worktree-lock-release-degrade-gate

## Context

worktree_manager 的 spec 锁是进程内存态（`core/worktree_manager/lifecycle.py`：`_spec_locks` 集合 + `_lock_since` 时间戳，键 `f"{spec_name}:{agent_type}"`）。run 被 supersede（如 planner-plan-1793009225 于 18:07 被 superseded）时锁不释放；后续同键派发命中「Worktree already active」→ adaptive backoff early give-up（lock age 7169s > peer estimate 900s，cap 1200s）→ 0.013s 秒败。pm_engine 的降级决策点（`core/pm_engine/engine.py` 约 ：2893-2936「新验证流程失败…降级到旧版 verifier（第 N 次降级）」）随即静默走 legacy 通道——legacy 通道 verdict 协议与消费守卫的失配即 fix-verify-verdict-run-attribution 所治问题的放大器。

## Goals / Non-Goals

**Goals:**
- supersede/终态后的同 agent_type 重派不再被陈锁秒败
- 异常路径泄漏的死锁主陈锁可被 acquire 侧安全清扫
- 连续静默降级有熔断，劣化对人工可见

**Non-Goals:**
- 不改锁的互斥语义与正常在飞期的 adaptive backoff 行为
- 不改持久化锁（锁仍为内存态，daemon 重启自然清零——本次 10-27 03:57 重启已实证）
- 不动 legacy verifier 本体（其 verdict 失配由 fix-verify-verdict-run-attribution 治理）
- 不做跨进程锁（超出需求，内存锁 + 重启清零语义维持）

## Decisions

- **D1 锁记录增 owner**：`_spec_locks` 的值语义从「在集合中」扩为 `锁键 → owner run_id`（新增 dict 或改结构均可），acquire 时记录当前 run_id——`create()` 增可选 owner_run_id 入参（调用点 core/agent_runner/runner.py:4223/4282 传 attempt run_id，缺省 None 维持现状），释放 API 校验 owner 一致才 discard，杜绝误放他人锁。释放失败（owner 不符）no-op + DEBUG。既有 `release_spec_lock(spec_name, agent_type)`（lifecycle.py:530，code-fix defer 车道既有 caller）扩展可选 owner 参数而非另立同名新 API：传 owner_run_id 时才做 owner 校验，不传维持既有幂等语义，defer 车道零改动。`_register_spec_locks`（core/worktree_manager/locks.py:74-77，无 run 上下文的登记写点）登记 owner=None 锁；D3 清扫对 owner=None 退回锁龄判据（缺 owner=无法核对存活，保守不清扫）。
- **D2 终态释放挂点**：run 收尾链（agent_runner 终态落账收口段，core/agent_runner/runner.py `_finalize_failure_keep` break 分支及同族收口）对失败类终态调用 `worktree_manager.release_spec_lock(spec, agent_type, owner_run_id)`。终态集合以框架单源 `RUN_TERMINAL_EVENT_TYPES`（core/agent_runner/liveness.py：非成功 result / error / interrupted / cancelled / frozen-terminated / gate-blocked）为准——框架无「failed」事件类型，失败经非成功 result/error 行表达。成功终态（success/completed）不释放——成功收尾的既有清理路径已覆盖，避免双释放。**中间弃置件 superseded（原地重试：superseded 行写在退避 sleep 之前、其后同链还有新 attempt，被 RUN_TERMINAL_EVENT_TYPES 故意排除）不挂终态释放**——退避窗口摘锁会让派发侧 has_active_lock 判空，重开同 spec:agent_type 并行派发窗口（2026-09-03 双派发事故形态，与 lifecycle.py 收尾入口时刻守卫同族不变量冲突）；该场景由 D3 acquire 清扫兜底（判据含 superseded 尾行）。
- **D3 存活判据双源**：acquire 早退段清扫判据 = ①run 记录（`.fenix/runs/<run_id>.jsonl` 非归档）末行属死亡判据集，或 ②run 记录不存在且派发窗口已过。①的「死亡判据集」= `RUN_TERMINAL_EVENT_TYPES` ∪ {"superseded"}——**比 liveness 存活判定的单源口径有意多收 superseded**：弃置件即持锁主已死（10-26 事故形态正是尾行为 superseded 的陈锁）；liveness 侧判「在飞」保守正确、清扫侧判「持锁主死亡」必须含弃置件，两处口径分叉是实现要点，不得为「复用单一真源」把 superseded 排除掉。②的「派发窗口已过」= 锁龄超过既有 adaptive backoff early give-up cap（1200s）。二者任一命中即清扫；判据不确定（记录在飞且末行非死亡判据行）维持既有早退；owner=None 登记锁（locks.py）退回②锁龄判据。锁记录需同时存 run_id 供判据查询（D1 顺带满足）。
- **D4 熔断计数与清零**：engine.py 降级决策点维护「连续降级计数」（spec 级，随 spec 状态存续）：首次降级放行 + 计数 +1；第 2 次直接 blocked + 升级告警（文案拼两次降级原因）。计数持久化于 spec STATE 条目（对齐 `_verify_fail_rounds` / `_env_block_rounds` 既有字段先例，state_machine.py:309/637）——engine.py:201-205 已证实例级/模块级计数不满足 spec 级语义（PMEngine 按 run 重建实例、模块级跨 spec 串扰），MUST NOT 落 PMEngine 实例属性或模块变量。清零点：验证轮成功推进 / admin 处置复位 / 人工解冻（与既有验证计数「人工解冻同写清零」同口径，复用 unfreeze_spec 的清零集，同一原子写）。
- **D5 告警通道**：熔断告警走既有 human-escalation-alert（verify_env_blocked 类），文案含 spec、两次降级原因、建议动作（核对 worktree 状态后重验）。

## Risks / Trade-offs

- **清扫误杀**：判据双源中「进程不存活」在 run 记录缺失分支才启用，主判据是记录终态行——活 run 必有在飞记录，误杀面收敛到记录系统本身故障场景；宁可保守（维持早退）已在 Requirement 中钉死。
- **熔断过紧**：连续 2 次降级即转人工，若网关抖动期连续失败会多几次人工介入；但每次转人工都附原因链，且解冻即重获预算，优于无限静默降级（本次事故形态）。
- **锁结构改动波及**：`_spec_locks` 从 set 改映射，同文件既有读点（日志、give-up 判定）需同步改；实现任务含既有 worktree 用例回归。
