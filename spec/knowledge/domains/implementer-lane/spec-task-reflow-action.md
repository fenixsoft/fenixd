<!-- knowledge: capability=spec-task-reflow-action rev=1 sources=spec/archive/2026-09-19-fix-impl-tasks-completion-gate -->

# SPEC 任务回炉动作

任务完成度门禁拦截滞留 SPEC 的产品化回炉入口：把 `verified` 滞留复位为 `ready` 重新派发，消除「人工直接改写 STATE.md」的无入口作业方式。

## 现行规则

- 入口形态：后端暴露 `POST /api/spec-task-reflow?project=<name>&spec=<name>`；`bin/fenix_cli.py` 提供 `reflow <spec> [--project <path>]` 子命令。两者语义完全一致（同一开放条件、同一执行语义、同一日志留痕），判定与执行收敛到单一实现点共用，不在 CLI 侧复写判定逻辑。错误语义对齐既有 `spec-error-clear`/`spec-freeze-config`/`spec-budget` 家族（project/spec 不存在 404；不满足开放条件返回明确原因且非 200 或 `ok:false`；成功返回 `ok:true`）。
- 开放条件（全部满足才允许执行）：目标 SPEC 存在于 STATE.md；`status` 恰为 `verified`；`error` 字段以 `TASK_GAP_ERROR_PREFIX`（`core/pm_engine/__init__.py`）开头（确系任务完成度门禁写入的结论）；未被冻结（`frozen` 标记为假）。
- 执行语义：经 `StateMachine.update_spec` 原子写回 `status = "ready"` 与 `error = null`（携带 `status` 的更新自动解除取消保持标记，与既有面板重派/admin 处置复位语义一致）。不改写 `tasks.md`、不修改实现尝试预算计数、不绕过 daemon 的后续派发闸门（依赖、`start_after`、退避、冻结检查照常生效）。
- 留痕：复位后在 `.fenix/PROJECT_LOG.md` 追加可追溯记录（含 SPEC 名、原状态、缺口任务清单、动作来源）。
- 幂等与拒绝：连续调用第二次返回明确拒绝原因（当前状态已不在可回炉形态），不产生第二次状态写入或重复日志；对 `ready`/`implementing`/`testing`/`blocked`/`done`/`pushed` 状态、`error` 非任务缺口前缀、或冻结态的调用均返回明确拒绝原因，不产生任何状态写入。
- CLI 退出码：成功时输出含 SPEC 名与新状态的提示并以退出码 0 结束；被拒绝时把拒绝原因写入 stderr 并以非零退出码结束；`--project` 缺少 `.fenix/STATE.md` 时报错非零退出、无副作用。

## 溯源

- [2026-09-19 2026-09-19-fix-impl-tasks-completion-gate](spec/archive/2026-09-19-fix-impl-tasks-completion-gate/) — 随任务完成度门禁配套确立回炉动作：API + CLI 双入口单实现、四项开放条件、原子复位语义与留痕
