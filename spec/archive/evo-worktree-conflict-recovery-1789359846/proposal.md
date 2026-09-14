# worktree-conflict-recovery — worktree 冲突恢复与降级诊断化

## 背景
日志实锤（`.fenix/logs/fenixd.log.1`）的链路为：`Worktree already active for <spec>:<agent_type>`（WARNING）→ `Failed to create worktree`（ERROR）→ dual-dispatch guard 放弃重试（WARNING）→ `新验证流程失败 … 降级到旧版 verifier`（WARNING）。实例：2026-09-06T00:57:36Z `add-verify-multi-kind-runner:planner-plan`。

据此修正本 SPEC 初稿的两处事实表述：

1. 降级**并非完全无痕**。既有链路已在降级 WARNING 中原样携带原因文本（`core/pm_engine/engine.py:1299-1303` 插值异常消息；异常消息由 `core/agent_runner/runner.py:2552` 带出 `(gave up: parallel run or manual freeze)`），且 `core/pm_engine/verification.py:1706 → :3452` 已把降级原因落盘为 `degrade_context.json`、经 `core/verify_report.py:143-153` 注入 Dashboard（`core/dashboard/data.py:3669`）。真正的缺口是**结构化**原因只覆盖 planner「场景无效」一条路径：异常驱动的降级路径（`verification.py:1676`、`:2082`）不写 degrade 上下文。
2. 实际观测到的伤害不止「无痕」：锁冲突被归为**死亡 run**。2026-09-06T06:51:20Z `add-spec-scheduling-controls` 记录 `预算豁免（死亡 run）… reason=no run-result file (error=Failed to create worktree (gave up: parallel run or manual freeze))`，即基础设施锁冲突按「run 异常死亡」处置（退预算 + 计 retry）。框架对同类基础设施故障已有先例——`provider circuit open` 不计 retry、不翻状态（`core/pm_engine/dispatch.py:1129-1139`），锁冲突未获同等待遇。

能力缺口收敛为三项：创建失败无锁归属诊断（活动 vs 残留不区分）；残留锁无安全清理重试；锁冲突无结构化原因且被误计入 run 死亡。

## 目标
- worktree 创建失败时先诊断锁归属：锁由活动 run 持有 → 明确判为并发（不重试、不清理）；锁为残留（同一 daemon 生命周期内孤儿持锁、持锁者已无对应进程）→ 安全清理后重试一次。
- 降级动作携带**结构化**原因字段，写入既有 degrade_context 通道（MUST NOT 新建通道），并覆盖异常驱动的降级路径。
- worktree 活跃记录含 run id 与创建时间，便于追溯残留来源；pid 仅作参考（见 design「活跃记录扩展」）。
- 锁冲突 MUST NOT 被当作「run 异常死亡」处置（不因此退预算、不因此计 retry）。

## 非目标
- 不改 worktree 的并发保护语义（dual-dispatch guard 保留）。
- 不改派发层既有的锁冲突退避与 `dispatch_stalled` 升级（`core/pm_engine/dispatch.py:79-132`）；两者职责边界见 design「与既有机制的关系」。
- 不新建降级观测通道（复用 `degrade_context.json → verify_report → Dashboard` 既有链路）。
- 不改 legacy verifier 读取路径（已在 verifier-result-single-source 覆盖）。

## 验收
- 残留锁冲突时可自动清理并重试成功；活动 run 冲突时降级原因字段为 `parallel-run` 且含活跃 run id。
- 不存在「锁冲突 → 按死亡 run 退预算」的归因（budget 审计日志中该 spec 不出现 `死亡 run` 豁免）。
- 覆盖 planner（`planner-plan`/`planner-judge`）agent_type：其 run 流转录前缀非 `impl-`/`verify-`，判定 MUST NOT 依赖 run 流 glob（见 design「残留判定」）。