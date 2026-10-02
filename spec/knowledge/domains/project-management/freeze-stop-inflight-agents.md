<!-- knowledge: capability=freeze-stop-inflight-agents rev=3 sources=spec/archive/2026-09-25-add-freeze-stop-inflight-agents,spec/archive/2026-09-26-fix-relocation-writeback-layer,spec/archive/2026-09-29-evo-alert-noise-governance -->

# 项目冻结即停在跑 Agent

冻结 SPEC 即在秒级内终止其名下全部在跑 agent，终止前保全现场、记录独立保持标记，解冻后在保留分支自动续做；冻结态下派发入口对新派任务一律跳过。

## 现行规则

- 轮询环冻结检查：`_run_claude` 轮询环（1 秒粒度）在 run-cancel 旗标检查处同时检查所属 SPEC 冻结态，读取 STATE 结构化 `frozen` 字段（与 `AgentRunner._spec_is_frozen` 同源），不依赖 error 文本前缀；判定异常 fail-open（不终止）。frozen 检查先于 run-cancel 检查（spec 级优先于 run 级）；命中时清理该 run 残留的 cancel 旗标，防止解冻续做被残留旗标立即再终止。
- 冻结终止序列：先对当前 worktree 执行 WIP checkpoint 保全（提交消息含 `fenix(wip):` 前缀与冻结锚点标识；保全失败仅 WARNING 不阻断；无 worktree 载体的 run 如 planner/judge 幂等跳过）→ `terminate()` → 等待最长 `AGENT_TERMINATE_GRACE_SECONDS`（10 秒）→ 仍存活则 `kill()`；读线程 join 后向 run 产物追加终态行，保证该行是文件最后一行。
- 独立终态类型：终态行为 `{"type": "frozen-terminated", "reason", "by", "timestamp"}`，不复用 `cancelled`；该类型必须同时登记写侧 `core/agent_runner/liveness.py::RUN_TERMINAL_EVENT_TYPES` 与读侧 `core/dashboard/data/runs.py::_RUN_TERMINAL_STATUS_MAP`（缺任一处会把已终止 run 永久判为 running）。终止由持有该 run 的 worker 线程在轮询环内执行，不跨线程 kill；抛独立异常 `FrozenTerminatedError`（携带 reason），不复用 `RunCancelledError`；`AgentRunResult.frozen_terminated: bool` 随序列化输出。
- 独立保持标记：STATE 布尔字段 `_frozen_hold` 与 `_cancelled_hold` 并列且互不读写，纳入序列化键表与布尔显式转换（`"False"` 字符串不得误判为真）。冻结终止写 `_frozen_hold: True` 与含「冻结」语义的保真 error 文案，不翻转 `status`（保持 `blocked`）、不写 `_cancelled_hold`，并先清除该 spec 的 `_cancelled_hold`；置位期间保留 `branch` / `implementer_run` 锚点不清空。
- 冻结保留续做锚点：`freeze_spec` 写 `blocked + frozen: True` 时不清空 `branch` / `implementer_run` / `reviewer_run`，锚点与冻结标记同一次原子写（或原地保留）。
- 不重试不重派：dispatch 对 `frozen_terminated=True` 的结果走独立冻结保持分支——不重试、不重派、不翻转 status、不动重试计数与合并指纹字段。覆盖全部经 dispatch 收口的 agent 类型（implementer / fast-track / verifier / repair / spec-review / planner / judge），与 `cancelled=True` 分支同宽；非 dispatch 收口角色（administrator / code-review / self-review / evolution）由 runner 层终止序列与文件信号取消覆盖，不为其新增 `_frozen_hold` 写点。
- 派发入口 frozen 复核：spec_ready 消费与派发准备（`_on_spec_ready`）守卫链含 frozen 检查，位于状态读取之后、内容完整性闸门校验之前——命中即记 INFO 跳过派发，冻结 spec 不重放「派发→闸门拦截→冻结」流程，daemon 重启后 `_diff_specs` 空快照整批回放 spec_ready 亦不例外。派发失败重试路径同口径：对 frozen spec 跳过重试，冷却/到期语义只对非冻结 spec 生效。人工 kick 走同一入口，冻结 spec 的人工重派同样须先解冻（「唯一出路是补内容后人工 unfreeze」契约），INFO 留痕保证操作者可见跳过原因。
- 停止覆盖全量在跑 run：冻结触发的停止动作按 spec 归属全等匹配（`run_spec_part(run_id) == spec`），禁用子串或前缀 glob，覆盖全部 agent 前缀（administrator / dispute-judge / spec-review / code-review / planner / planner-judge / implementer / fast-track / repair / verifier / tester）。
- 解冻续做保留判定：`unfreeze_spec` 恢复原状态时若 `_frozen_hold` 为真，先判定 `branch` 在册、分支可解析、相对 main 有未合并提交（`git rev-list --count main..<branch> > 0`）且载体可用；判定不得以调用方显式传入 `project_root` / `worktree_manager` 为前置条件——上下文缺失时由 spec 名自解析项目根后再判定。判定通过 → 输出与 `interrupt-recovery-preserve` 恢复保留同源的更新集（`status` 置原状态、保留 `branch` / `implementer_run`、置 `_recovery_resume: True`、清 `_frozen_hold`），dispatch 拾取后在保留分支 resume，不从零新建分支。
- 载体缺失不弃分支：worktree 已清理、只剩分支（在册 worktree 无命中）时，经分支命名空间枚举（`find_branches_by_spec`）定位保留分支并记录为续做分支（`branch` 锚点保留 / `_recovery_resume` 置位），dispatch 重建 worktree 后在该分支 resume；不得因载体缺失丢弃分支锚点转从 main 新建分支（将使保留分支不再被枚举、已交付实现被弃）。核心不变量：带 `_frozen_hold` 的解冻 ⇔ 保留分支被续做，或显式告警降级；不得静默丢弃保留分支锚点。
- 降级与既有清理：判定不通过（无 branch / 零提交 / 分支缺失）→ 清 `_frozen_hold`、不置 `_recovery_resume`、走普通重派并 WARNING 留痕。解冻既有清理行为（清 `error` / `frozen_until` / `frozen` 及各计数）保持不变；无 `_frozen_hold` 的解冻行为不受本能力影响。
- 前端反馈：冻结操作后行内提示已停止的 agent 计数（有在跑 agent 时），并说明进度已留存、解冻后可续做；无在跑 agent 时 MUST NOT 展示该类提示。

## 溯源

- 2026-09-25 add-freeze-stop-inflight-agents（spec/archive/2026-09-25-add-freeze-stop-inflight-agents） — 新增本能力：轮询环冻结检查、`frozen-terminated` 独立终态、`_frozen_hold` 保持标记、冻结保留锚点、dispatch 冻结保持分支与解冻保留分支续做
- 2026-09-26 fix-relocation-writeback-layer（spec/archive/2026-09-26-fix-relocation-writeback-layer） — 解冻保留判定去除对调用方上下文的前置依赖（自解析项目根）；worktree 已清理时经分支命名空间枚举续做，禁止因载体缺失丢弃保留分支转从 main 新建
- 2026-09-29 2026-09-29-evo-alert-noise-governance（spec/archive/2026-09-29-evo-alert-noise-governance） — 新增派发入口 frozen 复核（`_on_spec_ready` 守卫链、内容闸门校验之前）与派发失败重试路径的 frozen 跳过，冻结后不再新派、不重放闸门拦截流程
