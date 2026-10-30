# worktree spec 锁终态释放与陈锁清扫

<!-- knowledge: capability=worktree-lock-terminal-release rev=1
     sources=spec/archive/2026-10-30-fix-worktree-lock-release-degrade-gate -->

worktree spec 锁（`spec:agent_type`，进程内存态）的生命周期治理：run 失败终态即时释放锁、acquire 侧安全清扫陈锁——supersede/终止后的同 agent_type 重派不再被陈锁秒败。

## 规则

- **锁记录带 owner 归属**：spec 锁记录携带 owner run 归属（run_id，acquire 经 `create()` 的 owner_run_id 入参记录）；释放校验 owner 一致才 discard——终态 run 请求释放的锁 owner 与自身不符（锁已被其他 run 持有）时释放调用为 no-op 并落 DEBUG 留痕，MUST NOT 误放他人锁。无 run 上下文的登记写点登记 owner=None 锁。
- **终态释放**：run 到达失败类终态（框架终态单源 `RUN_TERMINAL_EVENT_TYPES`：非成功 result、error、interrupted、cancelled、frozen-terminated、gate-blocked）收尾时释放该 run 持有的对应锁；释放后同 spec 同 agent_type 的派发可立即正常 acquire，不出现「already active」早退。成功终态不释放（成功收尾的既有清理路径已覆盖，防双释放）。原地重试的中间弃置件 superseded（其后同链仍有新 attempt）MUST NOT 触发终态释放——退避窗口摘锁会让派发侧 has_active_lock 判空、重开同键并行派发窗口；该场景由 acquire 陈锁清扫兜底。
- **acquire 陈锁存活清扫**：acquire 因「already active」早退前核对持锁 run 存活性——确认死亡时清扫陈锁（discard + WARNING 留痕）并继续本次 acquire，MUST NOT 直接放弃。死亡判据：① run 记录（`.fenix/runs/<run_id>.jsonl` 非归档）末行属死亡判据集 = `RUN_TERMINAL_EVENT_TYPES` ∪ `{"superseded"}`——**有意比 liveness 存活判定多收 superseded**（弃置件即持锁主已死；liveness 侧判「在飞」保守正确、清扫侧判「持锁主死亡」必须含弃置件，两处口径分叉是实现要点，MUST NOT 以单一真源名义把 superseded 排除掉，与 ADR-299 词表分治一致）；或 ② run 记录不存在且锁龄超过 early give-up cap。存活判据不确定时（记录在飞且末行非死亡判据行）维持既有早退行为——宁可慢清扫不可错杀活锁；owner=None 登记锁退回②锁龄判据。
- **锁语义边界**：锁仍为进程内存态（daemon 重启自然清零）；互斥语义与正常在飞期的 adaptive backoff 行为不变；不做跨进程锁。

## 关键行为

治理对象是「锁泄漏放大链」：陈锁秒败（early give-up 0.013s）→ 新验证流程失败 → 静默降级 legacy verifier → verdict 协议失配放大浪费。本能力断第一环；降级兜底见 [legacy-degrade-prerequisite-gate](../verify-pipeline/legacy-degrade-prerequisite-gate.md)，verdict 失配治理见 [verify-verdict-run-attribution](../verdict-adjudication/verify-verdict-run-attribution.md)。

## 溯源

- 2026-10-30 fix-worktree-lock-release-degrade-gate（spec/archive/2026-10-30-fix-worktree-lock-release-degrade-gate） — 新增本能力：锁记录 owner 归属与终态释放（superseded 中间弃置件不释放防退避窗双派发）、acquire 陈锁存活清扫（死亡判据集有意含 superseded、不确定维持早退）（动因实测：planner-plan 被 supersede 后锁不释放，重出题派发被陈锁 0.013 秒秒败）
