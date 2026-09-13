## ADDED Requirements

### Requirement: task-gap 滞留 SPEC 的回炉动作

系统 MUST 提供一个产品化的人工回炉动作，把因 `verified → done` 任务完成度门禁（`_task_completion_blocker`）拦截而滞留在 `verified` 的 SPEC 复位为 `ready`，使其可被 daemon 重新派发实现者承接剩余任务。本动作 MUST 消除「人工直接改写 `.fenix/STATE.md`」这一无入口作业方式。

后端 MUST 暴露 `POST /api/spec-task-reflow?project=<name>&spec=<name>`，错误语义 MUST 对齐既有 `spec-error-clear` / `spec-freeze-config` / `spec-budget` 家族（project/spec 不存在 404、不满足开放条件返回明确原因且非 200 或 `ok:false`、成功返回 `ok:true`）。

**开放条件（全部满足才允许执行）**：

1. 目标 SPEC 存在于 STATE.md；
2. 其 `status` 恰为 `verified`；
3. 其 `error` 字段以 `TASK_GAP_ERROR_PREFIX`（`core/pm_engine/__init__.py:27`）开头——即确系任务完成度门禁写入的结论；
4. 该 SPEC 未被冻结（`frozen` 标记为假）。

**执行语义**：经 `StateMachine.update_spec` 原子写回 `status = "ready"` 与 `error = null`（`update_spec` 对携带 `status` 的更新会自动解除取消保持标记，语义与既有面板重派 / admin 处置复位一致）；MUST NOT 直接改写 `tasks.md`、MUST NOT 修改实现尝试预算计数、MUST NOT 绕过 daemon 的后续派发闸门（依赖、`start_after`、退避、冻结检查照常生效）。

复位后 MUST 在 `.fenix/PROJECT_LOG.md` 追加一条可追溯记录（含 SPEC 名、原状态、缺口任务清单、动作来源）。

#### Scenario: 合规形态复位为 ready

- **WHEN** 对状态为 `verified` 且 `error` 以 `task-gap:` 开头、未冻结的 SPEC 调用回炉接口
- **THEN** 接口返回 `ok:true`，该 SPEC 的 `status` 变为 `ready`、`error` 变为空，daemon 随后按既有逻辑派发实现者

#### Scenario: project 或 spec 不存在返回 404

- **WHEN** 以不存在的 project 或不存在的 spec 调用回炉接口
- **THEN** 返回 404，不产生任何状态写入

#### Scenario: 非 verified 状态被拒绝

- **WHEN** 对状态为 `ready` / `implementing` / `testing` / `blocked` / `done` / `pushed` 的 SPEC 调用回炉接口
- **THEN** 返回明确拒绝原因（指明当前状态不符），不产生任何状态写入

#### Scenario: error 非 task-gap 前缀被拒绝

- **WHEN** 对状态为 `verified` 但 `error` 为空、或以其它前缀（如 `spec-review-` / `冻结`）开头的 SPEC 调用回炉接口
- **THEN** 返回明确拒绝原因（指明未检出任务缺口结论），不产生任何状态写入

#### Scenario: 冻结态被拒绝

- **WHEN** 对处于人工冻结的 SPEC 调用回炉接口
- **THEN** 返回明确拒绝原因（指明冻结态须先解冻），不产生任何状态写入

#### Scenario: 幂等重复调用被拒绝

- **WHEN** 对同一 SPEC 连续调用两次回炉接口（第一次已成功复位为 `ready`）
- **THEN** 第二次返回明确拒绝原因（当前状态为 `ready`，已不在可回炉形态），MUST NOT 产生第二次状态写入或重复日志

#### Scenario: 回炉不触碰预算与冻结计数器

- **WHEN** 对一个 `_impl_run_budget_used` 已非零的 SPEC 执行回炉
- **THEN** 该计数值保持不变，`frozen` / `frozen_until` / `start_after` 字段均不被修改

### Requirement: CLI 回炉子命令

`bin/fenix_cli.py` MUST 提供 `reflow <spec> [--project <path>]` 子命令，语义与后端回炉接口**完全一致**（同一开放条件、同一执行语义、同一日志留痕），MUST NOT 在 CLI 侧复写一套判定逻辑——判定与执行 MUST 收敛到单一实现点供 API 与 CLI 共用。

成功时 MUST 输出含 SPEC 名与新状态的提示并以退出码 0 结束；被拒绝时 MUST 把拒绝原因写入 stderr 并以非零退出码结束。

#### Scenario: 合规形态经 CLI 复位成功

- **WHEN** 执行 `python3 bin/fenix_cli.py reflow <spec> --project <project_root>`，该 SPEC 满足全部开放条件
- **THEN** 命令输出复位成功提示（含新状态 `ready`），退出码 0，STATE.md 中该 SPEC 状态为 `ready`、error 为空

#### Scenario: 拒绝时非零退出并给出原因

- **WHEN** 对不满足开放条件的 SPEC 执行 reflow 子命令
- **THEN** stderr 输出具体拒绝原因，退出码非 0，STATE.md 不被修改

#### Scenario: 非 Fenix 项目目录报错

- **WHEN** `--project` 指向的目录缺少 `.fenix/STATE.md`
- **THEN** 命令报错并以非零退出码结束，不产生任何副作用
