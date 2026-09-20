## ADDED Requirements

### Requirement: 实现者车道结果文件硬门提示词可见性

`implementer`（full）与 `fast-track` 两个实现者车道的派发提示词 MUST 各自包含结果文件硬门契约段，
其内容 MUST 至少声明：

- 框架对本次 run 的成功判定 = 进程正常退出 **且** 结果文件（`<worktree>/.fenix-run-result.json`）
  已落盘且为可解析的非空 JSON；
- **收工前未写 / 文件为空 / 非法 JSON → 本次 run 判失败**并走原地退避重试（整轮 token 重烧）；
- **正文里的 JSON 不算交付**：框架不解析回复正文，只读文件；
- **先落盘再深入**：先写一份最小可判的结果文件，再做全量套件回归 / 交付物核实等收尾工作；
- 本车道无定时唤醒节拍（`ScheduleWakeup` 在非交互派发下不产生唤醒），但后台 Bash 任务的
  **完成通知真实可用**（与 `ScheduleWakeup` 不可用是两件事）；可能超过 600s 工具上限的长任务
  MUST 用**一次** `run_in_background: true` 启动（存在 600s 内必然返回的有界入口如
  `bin/run_full_suite.py --timeout 3600` 时 MUST 优先前台直接跑），然后等待完成通知或做无
  数据依赖的独立工作；MUST NOT 用 `sleep` / 周期性 `ps` 轮询模拟等待，MUST NOT 启动即忘。

> 注（fix-agent-lane-efficiency 5.4 同步）：原「无后台节拍可用……MUST NOT 采用『后台运行 +
> 轮询等待』的收尾编排」表述与 `long-task-foreground-wait` 能力契约矛盾（被模型读作「后台
> 等待即违规」而退化为 `sleep → echo RUNNING` 自旋），本处按 D4 口径修正——保留能力事实、
> 只改行为约束；`tests/test_impl_resultfile_contract.py:99` 断言锚点已同步更新。

契约段路径 MUST 按 agent_type 分派计算：实现者车道取该 run 的 worktree 根
`<worktree>/.fenix-run-result.json`；planner-plan / planner-judge / spec-review 三车道维持既有路径
语义不变。

#### Scenario: 两条实现者车道均注入契约段

- **WHEN** 分别以 `agent_type="implementer"` 与 `agent_type="fast-track"` 构建派发提示词
- **THEN** 两个提示词文本均包含结果文件硬门契约段，且段内出现「先落盘再深入」「正文里的 JSON
  不算交付」「判失败」三项要素

#### Scenario: 契约段路径按车道分派

- **WHEN** 构建实现者车道提示词（worktree 为 `/wt/impl-<spec>-<ts>`）
- **THEN** 契约段给出的结果文件路径为 `<worktree>/.fenix-run-result.json`（不是 planner 的
  `verify-progress` 路径）；同一构建过程中 planner-judge 车道给出的仍是
  `.fenix/verify-progress/<spec>/.fenix-run-result.json`

#### Scenario: 既有车道契约段不回归

- **WHEN** 分别为 planner-plan / planner-judge / spec-review 构建提示词
- **THEN** 三者仍包含结果文件硬门契约段，且各自结果文件路径与本次变更前逐字一致

#### Scenario: 契约段不破坏既有段序断言

- **WHEN** 构建 planner-judge 提示词（既有测试断言「场景静态缺陷情报」段先于「结果文件硬门」段）
- **THEN** 既有段序关系保持不变，新增的实现者车道注入不改变其它车道段序

### Requirement: 实现者重试轮 MUST 继承上轮真实死因

实现者车道（`implementer` / `fast-track`）被重派时，提示词的「上轮失败上下文」MUST 携带上一轮
**可归因的真实死因文本**，覆盖两类来源：

- 状态机记录的 `error` 字段（既有来源，经 `_prev_error_section` 注入）；
- 上一轮执行器的结构化诊断 `_impl_diagnosis`（含 `terminal` / `attribution` / `conclusion` /
  `progress`，经 `_impl_diagnosis_section` 注入）。

两类来源 MUST 均可达（当 `error` 为空但诊断存在时，诊断中的 `attribution` / `conclusion` MUST 仍
注入，使 agent 知道上轮为何终止）；**同一诊断字段在单次 prompt 中 MUST 只渲染一次**——不得因两段
并存而重复渲染 `attribution` / `conclusion` / `progress`。该去重是**字段级**判据：同一诊断字段
MUST NOT 被两段各自作为独立条目渲染（`_prev_error_section` 只渲染 `error` 原文、不追加诊断字段）；
因 `attribution` 的定义即 `final_error[:500]`（`dispatch.py:1538-1603`）而 `STATE.error` 同源写入的
也是 `final_error`（`dispatch.py:1319-1333`），`error` 原文**包含** `attribution` 子串属预期，
MUST NOT 计为重复渲染，MUST NOT 为满足去重而裁剪 / 丢弃 `error` 原文。判定「结果文件缺失」而重派的
轮次，契约段 MUST 使 agent 明确得知「上轮因未落盘结果文件被判失败」，而非仅知「任务未完成」。

（备注：2026-09-17 复核实测两段均已在实现者双车道注入——`prompt_builder.py:574/609` 与注入点
`:260`/`:263`/`:334`/`:336`；本要求因此以「可达性核实 + 单次渲染去重」为验收口径。）

#### Scenario: 结果文件缺失重派轮携带真实死因

- **WHEN** 某 spec 上一轮因硬门失败（error 含「结果文件缺失」）被重派，构建本轮提示词
- **THEN** 提示词的上轮失败上下文中出现「结果文件缺失」归因文本，agent 可据此优先补落盘

#### Scenario: error 为空但诊断存在时仍注入

- **WHEN** 状态机 `error` 为空、但上一轮已写入 `_impl_diagnosis`（含非空 `attribution`）
- **THEN** 提示词仍注入该诊断的 `attribution` / `conclusion`，不出现「无上轮上下文」的静默空段

#### Scenario: 诊断字段在单次提示词中不重复渲染

- **WHEN** `error` 与 `_impl_diagnosis` 同时非空，构建 implementer 重试轮提示词
- **THEN** 字段级去重成立：`_prev_error_section` 的输出除 `error` 原文外不含任何诊断字段条目，
  `_impl_diagnosis_section` 是唯一把 `attribution` / `conclusion` / `progress` 作为独立条目渲染的段
  （`error` 原文内含 `attribution` 子串系两字段同源，不计为重复渲染）

#### Scenario: 无上轮上下文时零注入

- **WHEN** 该 spec 首次派发（无 `error`、无 `_impl_diagnosis`）
- **THEN** 不注入上轮失败段，提示词与现状逐字一致（不含空标题段）

### Requirement: 实现者车道结果文件捞回

实现者车道（`implementer` / `fast-track`）run 正常收工但从未写结果文件时，若其转录末轮的 assistant
文本中含合法结果 JSON（fenced 代码块，`status` 在实现者白名单内），框架 SHALL 代写落盘到
`<worktree>/.fenix-run-result.json`，把「整轮白烧重派」降为「零成本回收」。

捞回 MUST 遵守既有守卫语义：

- 目标文件已存在 → MUST NOT 覆盖（不破坏既有产物）；
- 抽不出合法 JSON / `status` 不在白名单 → MUST NOT 落盘，交由硬门按既有语义判失败重试；
- 转录缺失或不可读 → MUST NOT 落盘、MUST NOT 抛异常；
- 落盘视图 MUST 与 agent 自写产物同构（顶层含 `spec` 戳），使后续读侧与硬门无需区分来源；
- 捞回时点 MUST 早于框架的 worktree→主树产物拷回（`runner.py:1963` 的拷回块），使既有拷回逻辑的
  `role` / `spec` 戳注入与主树副本写入对代写产物同样生效；
- 捞回动作 MUST 产生可观测日志（含 spec / run_id / `status`），MUST NOT 静默。

spec-review 车道既有捞回语义（路径、白名单）MUST 保持不变。

#### Scenario: 实现者 result 事件后正文含合法结果 JSON

- **WHEN** implementer run 自然退出（有 `result` 事件）、worktree 内结果文件不存在，末轮文本含
  fenced JSON 且 `status ∈ {success, partial, error}`
- **THEN** 框架代写落盘 `<worktree>/.fenix-run-result.json`，该轮不再判「结果文件缺失」，并写一条
  捞回日志

#### Scenario: 目标文件已存在不覆盖

- **WHEN** worktree 内结果文件已存在（本轮 agent 已写或复用 worktree 遗留）
- **THEN** 捞回不动作、不覆盖既有内容，走既有硬门判定路径

#### Scenario: status 非法不落盘

- **WHEN** 末轮文本的 fenced JSON 可解析但 `status` 不在 `{success, partial, error}` 内
- **THEN** 捞回返回失败、不落盘，硬门按「结果文件缺失」既有语义判失败并原地重试

#### Scenario: spec-review 捞回语义不回归

- **WHEN** spec-review run 未写结果文件、末轮文本含合法评审结果 JSON
- **THEN** 仍落盘到 `.fenix/spec-review/<spec>/.fenix-run-result.json`，白名单与行为与本次变更前一致

### Requirement: 结果文件缺失归因区分假工具调用与未收工即停

实现者车道因结果文件缺失判失败时，其 error 归因 MUST 复用既有终态机械特征（读 run 转录末轮
assistant 文本）区分两类死法：

- 文本含假工具调用特征（`<function_calls>` / `<tool_use` / `<parameter` / markdown fenced 工具名）
  → 归因「格式回退截断」；
- 无上述特征 → 归因「未收工即停」。

归因 MUST 只用于日志 / 告警语义区分，MUST NOT 改变处置路径（两者对原地重试与 resume 的正确性相同）。
归因判定 MUST 零 LLM、纯文本机械匹配；转录缺失 / 损坏时 MUST 降级为「未收工即停」且不抛异常。

#### Scenario: 假工具调用形态归因

- **WHEN** 结果文件缺失且末轮 assistant 文本含 `<tool_use name="ScheduleWakeup" ...>` 形态
- **THEN** 该轮 error 归因含「格式回退截断」，日志与告警可据此区分

#### Scenario: 正常停轮形态归因

- **WHEN** 结果文件缺失且末轮 assistant 文本为普通叙述（无假工具调用特征）
- **THEN** 该轮 error 归因含「未收工即停」

#### Scenario: 归因不改变处置路径

- **WHEN** 两类归因分别命中
- **THEN** 两者均进入既有原地退避重试通道，重试次数、退避序列与 resume 行为一致

#### Scenario: 转录缺失降级不抛错

- **WHEN** run 转录文件缺失或不可读
- **THEN** 归因降级为「未收工即停」，判定过程不抛异常、不阻断收口
