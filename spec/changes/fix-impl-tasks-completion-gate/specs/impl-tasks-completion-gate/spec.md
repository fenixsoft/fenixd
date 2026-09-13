## ADDED Requirements

### Requirement: 实现者与快速通道的结果产物硬门

runner 的产物硬门 `_check_agent_result_artifact(project_root, spec_name, agent_type, run_started_at, wt_path)` MUST 覆盖 `agent_type ∈ {"implementer", "fast-track"}`，不再对这两类直接返回 `None`。校验对象 MUST 是**本轮 run 的 worktree 根目录**下的 `.fenix-run-result.json`（不经主树拷回副本判定，避免读到上一轮残留）。

`exit 0` 时硬门 MUST 依次校验：文件存在；文件非空；内容为合法 JSON；顶层为对象（非数组/标量）；顶层 `status` 取值 ∈ 白名单 `{"success", "error", "partial"}`。任一不满足 MUST 返回失败归因文案（含具体文件路径与失败类别），由调用方抛 `AgentArtifactGateError`。

硬门本身 MUST NOT 判 run 失败、MUST NOT 消耗实现尝试预算、MUST NOT 触发 provider 冷却或失败重试递增。

#### Scenario: 结果文件缺失被硬门拦截

- **WHEN** implementer run 进程 exit 0，但 worktree 根目录下不存在 `.fenix-run-result.json`（模拟历史上 planner 侧出现过的"exit 0 零产物"形态）
- **THEN** 硬门返回含「结果文件缺失」语义与 worktree 路径的失败归因，run 不被标记 succeeded，抛 `AgentArtifactGateError`

#### Scenario: 结果文件非法 JSON 被硬门拦截

- **WHEN** implementer run 进程 exit 0 且文件存在，但内容为非法 JSON（如裸换行截断）或顶层为数组
- **THEN** 硬门返回含「非法 JSON」或「顶层非对象」类别的失败归因，run 不被标记 succeeded

#### Scenario: status 越白名单被硬门拦截

- **WHEN** implementer run 进程 exit 0，结果文件为合法 JSON 且顶层为对象，但 `status` 为白名单外取值（如 `"plan-ready"` 或任意字符串）
- **THEN** 硬门返回含实际读到的 status 取值（如 `status='plan-ready'`）的失败归因，run 不被标记 succeeded

#### Scenario: 健康轮次放行

- **WHEN** implementer run 进程 exit 0，worktree 内 `.fenix-run-result.json` 为合法 JSON、顶层对象、`status` 为 `"success"`，且满足本能力另两条需求声明的完成度判据
- **THEN** 硬门返回 None，run 按既有流程标记 succeeded

#### Scenario: fast-track 同门覆盖

- **WHEN** fast-track run 进程 exit 0 但 worktree 内结果文件缺失或 status 越白名单
- **THEN** 硬门在 fast-track 既有硬校验（`_hard_check_fast_track` 家族）之外同样返回失败归因，run 不被标记 succeeded

### Requirement: success 状态的任务书完成度判据

硬门 MUST 在 `status == "success"` 时叠加**任务书完成度判据**，在 `status == "partial"` 时叠加**申报一致性判据**，`status == "error"` 时 MUST NOT 施加任何完成度类判据。两类判据均以本轮 run 的 worktree 内 `spec/changes/<spec_name>/tasks.md` 为对象。

**`partial` 的申报一致性判据**（必选，防止 `partial` 成为绕过 `success` 判据的缺口）：结果文件 MUST 同时含 `completed_tasks` 与 `unfinished` 两个数组；`completed_tasks` 集合 MUST 等于 `tasks.md` 已勾选数字任务 id 集合；`unfinished` 集合 MUST 等于未勾选数字任务 id 集合；两集合 MUST 互斥且并集等于全部数字任务 id。任一不满足 MUST 返回失败归因。

**`success` 的完成度判据**：

1. **勾选清零**：`tasks.md` 中 MUST 不存在未勾选的数字任务，口径 MUST 与 `core/pm_engine/engine.py` 的 `_task_completion_blocker` **同源**（正则 `^- \[(x| )\] (\d+\.\d+)`），MUST NOT 另写第二套解析实现；`tasks.md` 缺失或不含数字任务时该项判定为通过（与既有门禁一致）。
2. **完成清单对账**：结果文件 MUST 含顶层 `completed_tasks` 数组（字符串形式的任务 id，如 `["1.1", "2.3"]`），且其集合 MUST 与 `tasks.md` 已勾选数字任务 id 的集合**完全相等**（缺项、多项、含非数字 id 均判失败）。

任一不满足 MUST 返回失败归因文案，文案 MUST 列出缺口任务 id 清单（最多前 20 个，其余以数量概括），使续做轮次的 prompt 可直接消费。

#### Scenario: 未勾任务残留被拦截（事故回归）

- **WHEN** implementer run 进程 exit 0、结果文件合法且 `status: "success"`，但 worktree 内 `tasks.md` 尚有 17 项数字任务未勾选（模拟 2026-09-13 `add-spec-review-gate` 事故形态：agent 主动收工并自报 success，收工总结里却列出剩余任务）
- **THEN** 硬门返回含「未完成任务」与缺口 id 清单的失败归因，run 不被标记 succeeded，抛 `AgentArtifactGateError`

#### Scenario: completed_tasks 与勾选项不一致被拦截

- **WHEN** run 进程 exit 0、`status: "success"`、`tasks.md` 全部勾选，但结果文件 `completed_tasks` 缺列其中一个已勾任务 id
- **THEN** 硬门返回含该缺口 id 的失败归因，run 不被标记 succeeded

#### Scenario: completed_tasks 缺失被拦截

- **WHEN** run 进程 exit 0、`status: "success"`、`tasks.md` 全部勾选，但结果文件无 `completed_tasks` 键
- **THEN** 硬门返回「完成清单缺失」类失败归因，run 不被标记 succeeded

#### Scenario: partial 申报不一致被拦截

- **WHEN** run 进程 exit 0、结果文件 `status: "partial"`，`tasks.md` 有 3 项未勾选，但 `unfinished` 只列了 2 项（或 `completed_tasks` 含其中一个未勾任务）
- **THEN** 硬门返回含不一致任务 id 的失败归因，run 不被标记 succeeded

#### Scenario: partial 申报一致则通过硬门

- **WHEN** run 进程 exit 0、结果文件 `status: "partial"` 且 `completed_tasks` / `unfinished` 与 `tasks.md` 勾选状态严格对应
- **THEN** 硬门返回 None（结果文件合法即通过），run 的终态由 dispatch 侧按非 success 语义处理

#### Scenario: error 不施加完成度类判据

- **WHEN** run 进程 exit 0、结果文件 `status: "error"` 且 `tasks.md` 存在未勾任务、无 `completed_tasks` 键
- **THEN** 硬门不因完成度或申报一致性判据拦截

#### Scenario: 无数字任务的 SPEC 放行

- **WHEN** run 进程 exit 0、`status: "success"`，但该 SPEC 的 `tasks.md` 不含任何 `x.y` 形式数字任务
- **THEN** 勾选清零项判定通过；`completed_tasks` 集合对账以空集为基准（须为空数组或缺失均视为通过）

### Requirement: TaskUpdate 交叉核对的能力探测与条件化

硬门 MUST 读取本轮 run 产物（`.fenix/runs/<run_id>.jsonl`）中 `type == "system"` 且 `subtype == "init"` 事件的 `tools` 数组做能力探测：

- 数组中含 `"TaskCreate"` 时，硬门 MUST 额外强制：`parse_run_task_done(run_file)["done_ids"]` MUST 覆盖 `tasks.md` 的全部已勾选数字任务 id；不满足即判失败，归因须注明「已完成任务与 TaskUpdate 记录不一致」。
- 数组不含 `"TaskCreate"`（或 `init` 事件不可得）时，硬门 MUST **跳过** 该项核对并放行，同时 MUST 向 run 产物追加一条 `type == "impl-task-crosscheck-skipped"` 的审计事件，携带 `spec`、`run_id`、`reason`。

硬门 MUST NOT 把该交叉核对实现为无条件硬要求——在 Task 家族工具不可用的派发路由上该判据不可满足，会形成「拒绝 → resume → 再拒绝」的预算烧穿循环（实测：`.fenix/runs/` 中 141 个 runner 派发的 run 里含真实 `TaskCreate`/`TaskUpdate` 调用的为 0，`init.tools` 含 `TaskCreate` 的仅 1 个且为非 runner 派发）。

#### Scenario: 工具可用时交叉核对生效

- **WHEN** run 的 `init.tools` 含 `TaskCreate`，`tasks.md` 全部勾选且 `status: "success"`，但 `done_ids` 为空集合
- **THEN** 硬门返回「已完成任务与 TaskUpdate 记录不一致」失败归因，run 不被标记 succeeded

#### Scenario: 工具不可用时跳过并留痕

- **WHEN** run 的 `init.tools` 不含 `TaskCreate`，其余完成度判据（勾选清零、completed_tasks 对账）全部满足
- **THEN** 硬门返回 None 放行该轮，且 run 产物中新增 `impl-task-crosscheck-skipped` 审计事件

#### Scenario: init 事件不可得时保守跳过

- **WHEN** run 产物文件缺失、无法解析或不存在 `init` 事件
- **THEN** 硬门按「工具不可用」处理——跳过交叉核对、写审计事件、不放行因该缺失而失败

### Requirement: 硬门失败走原地续做而非废弃整轮

硬门失败 MUST 复用既有 `AgentArtifactGateError` 通道（与 `add-impl-terminal-nocommit-gate` 同构）：保留 worktree 与 run 现场、按既有退避序列原地重试、以同一 worktree 与 `--resume` 会话续做，MUST NOT 清理 worktree、MUST NOT 把该轮判为"零成果需整轮重做"。

续做轮次的 prompt MUST 被注入硬门归因（缺口任务 id 清单与失败类别），使 agent 无需重新推导剩余范围。

#### Scenario: 失败后 worktree 保留并续做

- **WHEN** 硬门因 `tasks.md` 尚有未勾任务拦截一次 implementer run
- **THEN** worktree 不被清理，重试轮次以同 worktree、同 session `--resume` 启动，且其 prompt 含缺口任务 id 清单

#### Scenario: 续做轮完成后放行

- **WHEN** 续做轮次把 `tasks.md` 补齐至全部勾选、写出 `completed_tasks` 且 `status: "success"`
- **THEN** 硬门返回 None，run 正常 succeeded，后续 implemented → testing 链路不受影响

#### Scenario: 连续失败仍受既有重试上限约束

- **WHEN** 多轮续做后 `tasks.md` 仍存在未勾任务
- **THEN** 由既有 provider-transient 退避与实现尝试预算机制收口（不新增独立重试计数），最终按既有语义转 blocked 或失败重派

### Requirement: 硬门归因可诊断

硬门失败文案 MUST 指明失败的具体文件、失败类别（缺失 / 为空 / 非法 JSON / 顶层非对象 / status 白名单外 / 未完成任务 / 完成清单不一致 / TaskUpdate 不一致）与相关任务 id，MUST NOT 以 `None` 替代真实读到的取值。

#### Scenario: 归因含真实 status 取值

- **WHEN** 硬门因 status 越白名单失败
- **THEN** 失败文案包含实际读到的 status 字符串，便于人工与续做轮次直接定位

#### Scenario: 归因含缺口任务清单

- **WHEN** 硬门因未勾任务或完成清单不一致失败
- **THEN** 失败文案包含缺口任务 id 清单（超过 20 项时截断并标注总数）

### Requirement: partial 状态的消费点一致性

`partial` 是「诚实申报未完成」的合法终态，其语义 MUST 在全部实现者结果消费点显式落地，MUST NOT 落入"未知状态按成功/放行处理"的默认分支。

消费点（现址：`core/pm_engine/dispatch.py:729-740`（主路径）、`core/pm_engine/dispatch.py:1313`、`core/pm_engine/dispatch.py:2225` 与 `core/pm_engine/dispatch.py:3130`（fast-track 路径）、`core/pm_engine/verification.py:3287`、`core/pm_engine/engine.py:766` 的读取器及其调用方）MUST：

1. 判 `partial` 为**非成功**终态（`is_success` 为假，与 `error` 同侧），MUST NOT 放行 `implemented → testing`；
2. 生成**非空**的失败归因文案——归因 MUST 由 `unfinished` 清单与缺口任务 id 构成，MUST NOT 沿用 `result.error`（成功进程的 `error` 为 `None`，会产出"失败但无归因"的空壳处置，违背既有 admin 处置不得为空壳的约定）；
3. 走既有失败/重派通道并**消耗**实现尝试预算（与 `error` 同侧）——`partial` MUST NOT 走 `AgentArtifactGateError` 的不消耗预算原地续做通道，否则形成"申报 partial → 无限续做"的预算绕行；连续 `partial` 由既有预算上限收口并转 blocked 交人工。

`partial` MUST NOT 被任何消费点解读为"已完成部分即可推进"。

#### Scenario: partial 不放行到实现完成

- **WHEN** implementer run 以 `status: "partial"`、`unfinished: ["5.1","6.2"]` 结束且进程 exit 0
- **THEN** `is_success` 为假，SPEC 不进入 `implemented`，按失败重派

#### Scenario: partial 的归因非空且含缺口清单

- **WHEN** 上述 partial run 的失败被记录
- **THEN** 写入的错误字段包含 `5.1`、`6.2` 等缺口任务 id，MUST NOT 为 `None` 或空串

#### Scenario: partial 消耗实现尝试预算

- **WHEN** 连续多轮 run 均以 `status: "partial"` 结束
- **THEN** 每次均递增实现尝试预算计数，到达既有预算上限后按既有语义转 `blocked`，MUST NOT 无限重派

#### Scenario: partial 不误判为成功

- **WHEN** `partial` run 的分支有真实提交（零变更哨不构成拦截条件）
- **THEN** 仍按非成功处理，MUST NOT 因"有提交"而放行为成功
