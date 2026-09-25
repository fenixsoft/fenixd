# freeze-stop-inflight-agents — Spec

## ADDED Requirements

### Requirement: 冻结即停：轮询环检查 spec 冻结态

`_run_claude` 轮询环（1 秒粒度）MUST 在既有 run-cancel 旗标检查处同时检查该 run 所属 SPEC 的冻结态。检查 MUST 读取 STATE 的结构化 `frozen` 字段（与 `AgentRunner._spec_is_frozen` 同源），MUST NOT 依赖 error 文本前缀。判定异常 MUST fail-open（不终止），与既有 `_spec_is_frozen` 容错口径一致。

检查顺序 MUST 为：frozen 检查先于 run-cancel 旗标检查（spec 级优先级高于 run 级）。冻结命中时 MUST 清理该 run 残留的 cancel 旗标，防止解冻后续做被残留旗标立即再终止。

#### Scenario: 冻结后在飞 attempt 被终止

- **WHEN** 某 SPEC 处于 `implementing` 且有在跑的 implementer run，用户将其冻结（STATE 写 `blocked` + `frozen: True`）
- **THEN** 该 run 的轮询环在 ≤1 秒内命中冻结检查，执行终止序列（见「冻结终止序列」要求），run 产物末行落 `frozen-terminated` 终态行，agent 进程消失

#### Scenario: 未冻结的 spec 行为零变化

- **WHEN** 某 SPEC 未冻结（`frozen` 字段缺失或为 False）且正常在跑
- **THEN** 轮询环不触发冻结分支，run 按既有语义继续直至自然收工

#### Scenario: 冻结判定异常不误杀

- **WHEN** 读取 STATE 时抛异常（文件损坏/锁竞争）
- **THEN** 冻结检查返回 False（fail-open），run 不被终止，异常不影响既有轮询逻辑

### Requirement: 冻结终止序列与独立终态

冻结终止 MUST 复用 run-cancel 的终止序列形态：先对当前 worktree 执行 WIP checkpoint 保全，再 `terminate()`，等待最长 `AGENT_TERMINATE_GRACE_SECONDS`（10 秒），超时仍存活则 `kill()`；读线程 join 后向 run 产物追加终态行，保证该行是文件最后一行。

终态行 MUST 为独立类型 `{"type": "frozen-terminated", "reason", "by", "timestamp"}`，MUST NOT 复用 `cancelled`。该类型 MUST 同时登记进写侧权威 `core/agent_runner/liveness.py::RUN_TERMINAL_EVENT_TYPES` 与读侧映射 `core/dashboard/data/runs.py::_RUN_TERMINAL_STATUS_MAP`（两处同步，缺任一处会把已终止 run 永远判为 running）。

终止 MUST 由持有该 run 的 worker 线程在轮询环内执行，MUST NOT 由外部调用线程跨线程 kill。终止 MUST 抛独立异常 `FrozenTerminatedError`（携带 reason），MUST NOT 复用 `RunCancelledError`。

`AgentRunResult` MUST 增加 `frozen_terminated: bool = False` 字段并随序列化输出。

#### Scenario: 终止前保全 WIP

- **WHEN** 冻结命中且该 run 的 worktree 内有未提交改动
- **THEN** 终止序列先执行一次 WIP checkpoint 提交（消息含 `fenix(wip):` 前缀与冻结锚点标识），再终止进程；保全失败仅 WARNING 留痕，不阻断终止

#### Scenario: 宽限窗口内未退出则强杀

- **WHEN** 冻结终止发出 SIGTERM 后，agent 在 10 秒宽限内未退出
- **THEN** 对其执行 SIGKILL，随后正常落 `frozen-terminated` 终态行

#### Scenario: 无 worktree 载体的 run 照常终止

- **WHEN** 被冻结终止的 run 不持有 worktree（如 planner / judge 类）
- **THEN** WIP checkpoint 幂等跳过（不报错），终止序列照常执行

### Requirement: 冻结终止的独立保持标记

STATE MUST 新增布尔字段 `_frozen_hold`，与既有 `_cancelled_hold` **并列且互不读写**。该字段 MUST 纳入 STATE 的序列化键表与布尔显式转换（`"False"` 字符串不转换为布尔会被误判为真）。

`_frozen_hold` 为真时 MUST 同时保留 `branch` 与 `implementer_run` 锚点（不清空）。冻结终止路径 MUST 先清除该 spec 的 `_cancelled_hold`（避免解冻后恢复链路按取消保持跳过）。

冻结终止 MUST 写 `_frozen_hold: True` + 保真 error 文案（含「冻结」语义，供人工识别），MUST NOT 翻转 `status`（保持 `blocked`）、MUST NOT 写 `_cancelled_hold`。

#### Scenario: 冻结终止后标记与锚点齐备

- **WHEN** 某 implementing SPEC 的在跑 implementer 被冻结终止
- **THEN** STATE 中该 spec 为 `status: blocked`、`frozen: True`、`_frozen_hold: True`、`_cancelled_hold` 为 False，且 `branch` 与 `implementer_run` 保留原值（未清空）

#### Scenario: 取消保持不被冻结终止覆盖语义

- **WHEN** 某 spec 已带 `_cancelled_hold: True`，随后被冻结并触发冻结终止
- **THEN** 冻结终止写入 `_frozen_hold: True` 且将 `_cancelled_hold` 置为 False，两字段不同时为真

### Requirement: 冻结时保留续做锚点

`freeze_spec` 写 `blocked + frozen: True` 时 MUST NOT 清空该 spec 的 `branch` / `implementer_run` / `reviewer_run` 锚点；锚点必须与冻结标记同一次原子写（或原地保留），否则解冻续做判定（见「解冻后在保留分支自动续做」）在冻结终止之前就已失去全部锚点、只能降级为从零重派。

#### Scenario: 冻结不清锚点

- **WHEN** 某 spec 处于 `implementing` 且 `branch` / `implementer_run` 非空，用户将其冻结
- **THEN** 冻结后 STATE 中 `branch` / `implementer_run` 仍为原值（未清空），`status: blocked`、`frozen: True`

### Requirement: 冻结终止结果不重试不重派

dispatch 侧对 `frozen_terminated=True` 的 run 结果 MUST 走冻结保持分支：不重试、不重派、不翻转 status、不动重试计数与合并指纹字段，并写 `_frozen_hold` 标记。该分支 MUST 独立于既有的 `cancelled=True` 分支（`_cancelled_hold` 写入点），MUST NOT 复用同一代码路径。

覆盖范围 MUST 包含该 SPEC 名下全部**经 dispatch 收口**的 agent 类型的终止结果收口路径（implementer / fast-track / verifier / repair / spec-review / planner / judge），与既有 `cancelled=True` 分支的覆盖范围同宽。**非 dispatch 收口的角色**（administrator / code-review / self-review / evolution）无 spec 级收口分支，其冻结终止由 runner 层终止序列与文件信号取消覆盖即可，MUST NOT 为其新增 `_frozen_hold` 写点。

#### Scenario: 冻结终止不触发重派

- **WHEN** implementer run 返回 `frozen_terminated=True`
- **THEN** dispatch 记录 error 与 `_frozen_hold: True`，不入队任何后续条目、不清零/不递增 retry 计数、spec 保持 `blocked`

#### Scenario: 评审 run 冻结终止同样覆盖

- **WHEN** spec 处于 `reviewing`（评审 run 在跑）时被冻结终止
- **THEN** 评审结果分支识别 `frozen_terminated=True`，写 `_frozen_hold: True` 且不重派评审

### Requirement: 解冻后在保留分支自动续做

`unfreeze_spec` 恢复原状态时，若该 spec 的 `_frozen_hold` 为真，MUST 先做保留判定：`branch` 在册、分支可解析、且相对 main 有未合并提交（`git rev-list --count main..<branch> > 0`）、且 `resolve_resume_site` 判定载体可用。判定通过 → MUST 输出与 `interrupt-recovery-preserve` 的恢复保留**同源**的更新集：`status` 置为原状态、保留 `branch` / `implementer_run`、置 `_recovery_resume: True`、清 `_frozen_hold`。

判定 MUST 复用既有保留判定实现（提取为共享函数或直接委托），MUST NOT 复制一份平行副本（前缀表 / 分支解析口径漂移已有多次事故先例）。

判定不通过（无 branch / 零提交 / 载体不可用）→ MUST 清 `_frozen_hold`、不置 `_recovery_resume`、走普通重派，并 WARNING 留痕。

解冻的既有清理行为（清 `error` / `frozen_until` / `frozen` 及各计数）MUST 保持不变。

#### Scenario: 解冻命中保留分支续做

- **WHEN** 某 spec 带 `_frozen_hold: True` 且其保留分支相对 main 有未合并提交，用户解冻
- **THEN** STATE 恢复为冻结前状态、`branch`/`implementer_run` 保留、`_recovery_resume: True`、`_frozen_hold: False`；dispatch 拾取后在保留分支的 worktree 上 resume 续做，不新建分支

#### Scenario: 无保留成果走普通重派

- **WHEN** 某 spec 带 `_frozen_hold: True` 但其分支无未合并提交（或分支缺失）
- **THEN** 解冻后清 `_frozen_hold`、不置 `_recovery_resume`，spec 按原状态正常派发（从零），并留有 WARNING 记录降级原因

#### Scenario: 无 _frozen_hold 的解冻行为不变

- **WHEN** 解冻一个从未被冻结终止的 spec（`_frozen_hold` 缺失）
- **THEN** 解冻行为与改动前逐位一致，不触发任何续做接线

### Requirement: 停止动作覆盖该 SPEC 名下全部在跑 run

冻结与删除触发的停止动作 MUST 按 spec 归属匹配目标 run，归属判定 MUST 用全等比较（`run_spec_part(run_id) == spec`），MUST NOT 使用子串或前缀 glob。覆盖 MUST 包含全部 agent 前缀（administrator / dispute-judge / spec-review / code-review / planner / planner-judge / implementer / fast-track / repair / verifier / tester）。

#### Scenario: 前缀相似的兄弟 spec 不被误伤

- **WHEN** `fix-x` 与 `fix-x-y` 同时有在跑 run，对 `fix-x` 触发停止
- **THEN** 只停止 `fix-x` 名下的 run，`fix-x-y` 的 run 不受影响

#### Scenario: 非主链路 agent 同样被停止

- **WHEN** 某 spec 同时有在跑的 implementer 与 spec-review run，触发冻结
- **THEN** 两个 run 均被停止（不限于实现主链路）

### Requirement: 前端冻结的停止反馈

SPEC 列表的冻结操作后 MUST 行内反馈已停止的 agent 计数（有在跑 agent 时），并说明进度已留存、解冻后可续做。无在跑 agent 时 MUST NOT 展示该类提示，交互与现状一致。

#### Scenario: 冻结后的停止提示

- **WHEN** 用户冻结某有在跑 agent 的 SPEC
- **THEN** 提示已停止 N 个在跑 agent（并说明进度已留存，解冻后可续做）

#### Scenario: 无在跑 agent 时不展示停止提示

- **WHEN** 用户冻结一个无在跑 agent 的 SPEC
- **THEN** 不展示「停止 N 个 agent」类提示，交互与现状一致
