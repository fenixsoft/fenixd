# add-freeze-stop-inflight-agents — Design

## Context

**现有能力盘点（避免重复造轮子）**

| 机制 | 位置 | 现状 |
|------|------|------|
| run 粒度人工取消 | `AgentRunner.cancel_run` + `_cancel_requested` 旗标集合 + `_run_claude` 轮询环检查 | 成熟：登记旗标 → 属主线程 terminate/grace/kill → 落 `cancelled` 终态行 |
| 冻结的边界守卫 | `_attempt_top_guards` / `_should_give_up_before_retry` | 只覆盖 attempt / 重试**边界**，不覆盖在飞 attempt |
| 在飞进程管束 | `_run_claude` 轮询环（1s 粒度） | **只查 `_cancel_is_requested`**，不看 spec 的 frozen 字段 |
| WIP 保全 | `core/wip_checkpoint.py`（锚点 A/B/C/extension-tail） | 成熟：`fenix(wip): checkpoint <anchor> <spec>` |
| 保留分支续做 | `_recovery_preserve_spec` + `_recovery_resume` 标记 + `resolve_resume_site` 三态 | 成熟：daemon 重启中断恢复通道 |
| 取消保持 | `_cancelled_hold` 标记 + 全部恢复/派发链路的跳过守卫 | 成熟，但语义是「人工取消、有意等待」 |
| 删除保护 | `soft_delete_spec` 的 120s mtime 硬拦 | 只拒绝，不停止，无推进手段 |

**约束**

- `_run_claude` 轮询环是**唯一**能终止在飞 agent 进程的位置（同 `cancel_run` 的「属主线程执行终止」不变量，调用线程不做跨线程 kill）。
- 冻结是 spec 级、取消是 run 级，两者可同时存在；必须定义优先级与共存语义。
- dashboard 是独立进程，与 daemon 通过文件信号通信；`hosting_state != "managed"` 时信号无人消费。
- `INTERRUPTED_STATES` 含 `reviewing`（评审中断），故冻结终止必须对未登记 run 前缀同样成立（评审 run 前缀 `spec-review-`）。

## Goals / Non-Goals

**Goals**

- 冻结一个 SPEC → 其名下**全部**在跑 agent 在 ≤1 秒（轮询粒度）+ ≤10 秒（终止宽限）内停止。
- 停止前保全现场（WIP checkpoint），解冻后在保留分支上**自动**续做（非从零重做）。
- 冻结终止为独立终态，与人工取消语义不混淆、互不干扰。
- 删除 SPEC 时先停 agent 等终态再软删除；交互为异步受理，不阻塞浏览器。

**Non-Goals**

- 不改既有 run-cancel 语义与 `_cancelled_hold` 契约。
- 不新建第二套保全/续做机制（复用 `wip_checkpoint` + `_recovery_resume`）。
- 不处理 daemon 完全未运行（`stopped`）时的删除——此时无在跑 agent，直接软删除即可。
- 不做「冻结其他项目 daemon 未托管」的补救（沿用既有托管态前置校验）。

## Decisions

### D1：在轮询环加 frozen 检查，不新增文件信号

**决定**：`_run_claude` 轮询环在 `_cancel_is_requested(base_run_id)` 旁增加 `self._spec_is_frozen(spec_name)` 检查。

**理由**：`freeze_spec` 写的是 STATE.md，daemon 每轮主循环经 watcher / full_scan 感知——但轮询环是**进程内**的，直接读 STATE 只需一次文件读（`read_one`）。若走文件信号（如新增 `freeze_stop_request.json`），需要 dashboard → daemon → runner 三段接力，且冻结来源不止 dashboard（CLI、admin 处置、恢复链路都写 frozen），文件信号覆盖不全。

**替代方案**：新增 run-cancel 复用——把冻结翻译成对每个在跑 run 的 `cancel_run`。**否决**：① 语义错位（取消是 run 级人工动作，写 `_cancelled_hold` 会让解冻后无法续做）；② 需要 daemon 侧枚举该 spec 的全部在跑 run 并逐个写信号，多一跳且竞态窗口更大。

**代价（实测）**：本项目 `.fenix/STATE.md` 实测 **278,834 字节 / 272 条 spec**，`read_one`（内部 = `read_all` 全量解析，无单条索引）单次约 **13ms**（本机实测 3 次取均值）。轮询环每 1 秒 × 在跑 run 数 = 每在跑 run 约 1.3% CPU 用于重复解析同一文件。上限可控（并发 run 数十级），但**禁止**把 `_spec_is_frozen` 引入 `_execute_agent` 的重试子循环细粒度位置（会让调用频次从「1s」升到「子循环每次失败」）。若成为热点，后续可在 `_spec_is_frozen` 内加 2~3 秒 TTL 缓存（本 SPEC 不做，避免引入观测盲区）。

### D2：冻结终止走独立异常与独立终态行

**决定**：新增 `FrozenTerminatedError`（与 `RunCancelledError` 并列）、run 产物追加 `{"type": "frozen-terminated", ...}` 终态行、`AgentRunResult` 增加 `frozen_terminated: bool` 字段。

**理由**：若复用 `RunCancelledError`，dispatch 侧会走 `_cancelled_hold` 分支 → 解冻后 `_cancelled_hold` 会让恢复链路跳过该 spec（`recover_interrupted` 的 `_cancelled_hold` 跳过守卫），与「解冻后续做」直接冲突。

**终态行类型命名**：`frozen-terminated` 需**同时**登记进 `core/dashboard/data/runs.py::_RUN_TERMINAL_STATUS_MAP`（否则 dashboard 永远把该 run 判成 running）与 `core/agent_runner/liveness.py::RUN_TERMINAL_EVENT_TYPES`（写侧权威）。两处必须同步（既有测试锁两侧同步）。

**落盘位置（实测约束）**：`_run_claude` 的 `finally` 段既有次序为 `join 读线程 → result 行 → cancelled 行 → run_metrics 行`（`runner.py:3846/3850` 与 :3794），`run_metrics` 不是终态事件、不影响 `classify_run` 的末行判定（其 `_RUN_TERMINAL_STATUS_MAP` 不含该类型 → 判 running）。`frozen-terminated` 行 MUST 与 `cancelled` 行同位置（`finally` 内、join 之后），MUST NOT 放在 `run_metrics` 之后当作「真正的最后一字节」——既有口径是「末行终态」，`run_metrics` 追加在终态行之后是既有常态，不必也不应改变。

### D3：`_frozen_hold` 标记与 `_cancelled_hold` 并列，解冻时清除

**决定**：STATE 新增布尔字段 `_frozen_hold`，纳入布尔显式转换分支（`"False"` 不转会误判；字段名 `_` 前缀，`serialize` 的「`_` 前缀全量透传」分支已覆盖落盘，无需改显式键表）。

**风险（已实测）**：`tests/test_cancel_holdstate_recovery.py::CancelFinalizeMarkerContract` 以「注释含 hold-state + 人工取消」定位 6 处 `_cancelled_hold` 写点，并断言**全库 `'"_cancelled_hold": True'` 字面命中总数恰好 6 处**（`test_no_new_holdstate_write_point_missed`）。`mark_frozen_hold` 单次原子写 `{_frozen_hold: True, _cancelled_hold: False, "error": ...}` 是**清零点**而非保持写点，故不增加该字面命中数；若实现改为「两字段同写 True」或新增 `"_cancelled_hold": True` 字面，该静态守卫会立即红灯——本 SPEC MUST 保持「写 `_frozen_hold: True` + 清 `_cancelled_hold` 为 False」的形态。

**语义**：被冻结终止 → `_frozen_hold: True` + 保全锚点（`branch` / `implementer_run` 保留不清）。冻结期间 `_frozen_hold` 与 `frozen` 并存。

**与 `_cancelled_hold` 的分工**：
- `_cancelled_hold`: 人工取消 run → 有意等待态，**唯一出路是显式复位**（`update_spec` 携带 status）。恢复链路跳过。
- `_frozen_hold`: 冻结终止 → 现场已保全，**出路是 unfreeze**（清 `frozen` + 清 `_frozen_hold` + 置 `_recovery_resume`）。恢复链路不因它跳过（冻结期间由 `frozen` 字段挡住一切派发，`_frozen_hold` 只是续做依据）。

**为何不合并**：两者生命周期不同（取消保持由人工复位解除；冻结保持由 unfreeze 解除），合并会让 `unfreeze_spec` 必须判断「这个 hold 是取消来的还是冻结来的」，把简单问题复杂化。

### D4：解冻续做复用 `_recovery_preserve_spec` 同源判定

**决定**：`unfreeze_spec(status=orig)` 时若 `_frozen_hold` 为真，走与 `_recovery_preserve_spec` **同源**的分支解析与闸门判定（`branch` 存在 + `git rev-list --count main..<branch> > 0` + `resolve_resume_site` 载体可用）→ 输出等价更新（`status=orig`、`branch`/`implementer_run` 保留、`_recovery_resume: True`、`_frozen_hold: False`）。

**实现路径**：把 `_recovery_preserve_spec` 的判定主体提取为可复用函数（或让 `unfreeze_spec` 委托它），**不复制一份漂移副本**——这是本次重构的核心风险点，既有事故（评审前缀表漂移、`-r<n>` 剥除口径漂移）都源于复制。

**分支不可用降级**：无 branch / 零提交 / 载体不可用 → 清 `_frozen_hold` + `_recovery_resume` 不置，走普通重派（从零），并 WARNING 留痕。

### D5：删除 → 异步受理 + 有界等待终态

**决定**：
- `soft_delete_spec` 增加「先停再删」语义：枚举该 spec 在跑 run（`_running_agents` 同源归属）→ 逐个请求终止 → 有界等待终态（宽限 ≤10s/run + 总上限）→ 软删除。
- API `/api/spec-delete` 改为**异步受理**：托管态校验 → 写停止请求信号 → 立即 202 `{accepted: true, stopping: N}`；实际停止+删除由 daemon 消费信号后完成。
- 前端收到 202 后 toast「已受理，正在停止 N 个进行中的 agent」+ 轮询刷新，spec 行消失即完成。

**理由**：同步等待会让 HTTP 请求阻塞 10~30 秒（浏览器/连接超时风险）；异步受理与框架既有文件信号模式（`admin_invoke_request` / `approve_push_request`）一致。

**替代方案**：dashboard 进程直接调 `soft_delete_spec` 并阻塞轮询。**否决**：dashboard 与 daemon 是**不同进程**，`_running_agents` 在 daemon 内存里，dashboard 无法直接终止；只能经信号。

**信号设计**：复用/扩展 `cancel_run_request.json` 的单 run 形态不适用（需 spec 级 + 后续删除动作），新增 `spec_delete_request.json`（含 `spec` / `source` / `created`），由 daemon 主循环消费：停 agent → 等终态 → 调 `soft_delete_spec`。

**无在跑 agent 时**：直接同步软删除返回 200（保持既有交互，不引入无谓的异步往返）。

### D6：冻结/停止的归属匹配用全等，不用子串

**决定**：某 run 是否属于该 spec 用 `run_spec_part(run_id) == spec`（全等），复用 `core/agent_runner/run_files.py::run_spec_part`（已剥前后缀）。

**理由**：子串/前缀 glob 已两次出事——`fix-robustness-edge-cases`（`*fix-x*` 命中 `impl-fix-x-y-*` 误拦删除）、`fix-dashboard-read-path-performance`（`-r<n>` 漏剥）。全等是既有唯一正确口径。

## Risks / Trade-offs

- **[轮询环每轮多读 STATE.md]** → 每 1 秒 × 在跑 run 数；实测 STATE.md 278KB / 272 spec，`read_one` ≈13ms/次（见 D1「代价（实测）」）。若成为热点，后续可在 `_spec_is_frozen` 内加 2~3 秒 TTL 缓存（本 SPEC 不做，避免引入观测盲区）。
- **[冻结终止与 run 自然收工竞态]** → run 恰在冻结瞬间完成：轮询环先 `poll()` 到已退出则走正常收工路径（`success` 分支），frozen 检查不触发；顺序上把 frozen 检查置于 cancel 检查旁、`poll()`（`runner.py:3724` `rc = proc.poll()`）**之前**，保证「冻结已写但 run 已退」时按自然结果处理，不误判。
- **[冻结终止与取消旗标同时命中]** → 优先级：frozen 检查在 cancel 检查**之前**（spec 级 > run 级）。若已登记 cancel 旗标又冻结，走 frozen 路径并清理 cancel 旗标（防止解冻后续做时被残留旗标立即再杀）。
- **[_frozen_hold 与 _cancelled_hold 同时为真]** → 冻结终止路径 MUST 先清 `_cancelled_hold`（否则解冻后恢复链路跳过）；反向（取消后冻结）不需要，因为冻结终止会重新写 STATE。
- **[每次 attempt 都会再查一次 frozen，冻结期间重派被挡]** → `_attempt_top_guards` 的 frozen 分支（`runner.py:2716`）返回**失败** `AgentRunResult`，`_finalize_failure_keep` 见 `attempt == max_retries` 即 `break`，不 sleep(10)、不进下一 attempt。真正的挡板是派发侧（`_on_spec_ready` 读 `frozen` 跳过、`_should_give_up_before_retry` 让位）；但冻结若与在途 `_enqueue` 撞上，本路径会消耗一次 attempt——与既有 frozen 语义同源，本 SPEC 不改变，仅在此写明以避免误判为新增回归。
- **[删除信号无人消费（daemon 未托管/未运行）]** → API 前置 `hosting_state` 校验：`unmanaged` → 409 明确拒绝（对齐 `request_spec_approve_push`）；`stopped` 且无在跑 agent → 直接同步软删除（无 agent 可停）。
- **[删除等待期间用户重复点击]** → 信号文件已存在 → 409 冲突（对齐 `request_run_cancel` 语义）。
- **[冻结后 daemon 重启]** → `recover_interrupted` 遍历 `INTERRUPTED_STATES`（`{implementing, testing, reviewing}`），冻结 spec 已是 `blocked`（不在集合内）故不恢复；`_frozen_hold` 与 `frozen` 随 STATE.md 持久化，解冻续做不依赖 daemon 生命周期。
- **[保全依赖 worktree 有效]** → 无 worktree 载体（如 planner/judge 不建 worktree）时 `commit_wip_checkpoint` 幂等跳过（已有契约），不阻断终止。
- **[冻结终止的 worktree 处置：既有失败分型对 implementer 会销毁现场]** → `_finalize_failure_keep`（`runner.py:3029-3030`）对**非** fast-track/repair/`[provider-transient]` 的终态失败走 `cleanup(success=False)`，对 implementer 会**删除 worktree 目录**。本节 1.6 的「保留现场」要求正是为此：冻结终止 MUST 走 `keep_for_reuse`/`handed_off` 分支（同 `shutdown_interrupted` 形态），MUST NOT 落入 `cleanup`。
- **[遗产宽限期回收分支的风险]** → `keep_for_reuse` 走 `register_legacy`，其宽限期 `LEGACY_GRACE_SECONDS = STALE_LOCK_IDLE_SECONDS = 120s`；`cleanup_stale_worktrees()` 只在 daemon 启动时调用（`fenixd.py:494`），故进程内不会中途回收。但清理器 `_reclaim_expired_legacy` **不例外**地 `git branch -D <branch>`（`legacy_registry.py:354-359`），且 `_branch_protected_by_state` 只认 `implementing/implemented/testing/ready+_recovery_resume`——**冻结 spec 是 `blocked`，不在豁免集内**。因此冻结终止后若在超过 120s 内重启 daemon，解除冻结前该保留分支可能被回收、解冻时降级为从零重派。缓解（本 SPEC 采纳）：把冻结终止的 worktree 登记进**同一**「在册 worktree」语义（`register_legacy` 的路径形态即「目录保留」），并复用 `_branch_protected_by_state` 的分支保护口径扩展一条「`frozen` 且 `_frozen_hold` 的 spec 的 `branch` 保留」判据（落在 `core/worktree_manager/stale_sweep.py`，见 tasks 2.7）；未命中该判据时降级路径本身有 WARNING 留痕，不产生数据不一致。

## Migration Plan

- **无数据迁移**：`_frozen_hold` 是新字段，存量 spec 缺失即视为 False（`update_spec` 布尔转换 + 读侧 `.get()` 兜底）。
- **终态行新类型**：`frozen-terminated` 加进读侧映射后，存量 run 产物不含该类型，零影响。
- **回滚**：回滚只需还原 `_run_claude` 轮询环的 frozen 检查（其余为增量字段与新增信号，无副作用）。若已产生 `_frozen_hold: True` 的 spec，回滚后 unfreeze 不再续做（清标记走普通重派），不会卡死。
- **部署顺序**：daemon 与 dashboard 独立重启。dashboard 侧异步受理后，即使 daemon 仍旧代码，也存在短暂的「受理了但没人消费」窗口——由 409 冲突与重试兜底，不产生数据损坏。

## Open Questions

- 无。设计所需的全部决策已在 D1~D6 定案。
