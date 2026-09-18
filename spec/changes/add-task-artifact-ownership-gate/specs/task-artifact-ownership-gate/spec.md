# Spec: task-artifact-ownership-gate

## ADDED Requirements

### Requirement: 验证产物归属表

框架 SHALL 维护一份声明式的「验证链产物 → 归属车道」归属表作为单一真相源，供 lint 侧与起草自检侧共用，避免多处枚举漂移。

归属表至少 MUST 覆盖以下产物与归属：

- `.fenix/verify-progress/<spec>/test_scenarios.json` → 归属 `planner-plan`（`fast-track` 亦为合法产出车道）
- `.fenix/verify-progress/<spec>/scenarios.json` → 归属 pm_engine 持久化写侧（`fast-track` 亦为合法产出车道）
- `.fenix/verify-progress/<spec>/report.json` → 归属 `verify_engine`
- `.fenix/verify-progress/<spec>/.fenix-run-result.json` → 归属 `planner-judge`
- `<worktree>/.fenix-run-result.json` → 归属 `implementer` / `fast-track`（实现者自己的收工票据，合法交付）

`implementer` 车道 MUST NOT 被登记为上述任一验证链产物的归属车道。

#### Scenario: 归属表覆盖核心验证产物

- **WHEN** 代码加载归属表
- **THEN** 表中含 `test_scenarios.json`/`scenarios.json`/`report.json`/`planner-judge` 结果文件四条验证链产物条目
- **AND** 每条条目的归属车道集合中不含 `implementer`

### Requirement: 任务行产物归属校验

`lint_tasks_text` SHALL 在 tasks.md 可解析性判定之外，额外对每条任务行执行「产物归属」校验：命中验证产物路径引用，且该任务行**未指向任何代码文件**时判违规。

判据 MUST 同时满足两个条件才判违规（零误拦取向）：

1. 任务行文本命中验证链产物路径标识（至少含 `.fenix/verify-progress`、`test_scenarios.json`、`scenarios.json`、`report.json`、`.fenix-run-result.json` 之一）；
2. 任务行**未**指向任何代码文件——即不出现代码扩展名（`.py`/`.ts`/`.tsx`/`.js`/`.jsx`/`.md`/`.yaml`/`.yml`/`.json`/`.sh`）或已知代码路径特征（`core/`、`agents/`、`tests/`、`bin/`）。

仅命中其一 MUST NOT 判违规——「写代码让框架产出该文件」的合法任务（如「新增 `_write_impl_result_snapshot` 落盘快照到 verify-progress」）必须放行。

#### Scenario: 要求实现者持久化他车道产物判违规

- **WHEN** tasks.md 含任务行 `- [ ] 6.2 写 .fenix-run-result.json，并持久化场景集与结果到 .fenix/verify-progress/<spec>/`（行内无任何代码文件引用）
- **THEN** `lint_tasks_text` 返回违规，消息点名该任务行 id 与所命中的验证产物路径
- **AND** 违规消息给出纠正处方：改写为「实现 X 让框架产出该文件」或移出任务书（reference / `.fenix/todo.md` 人工步骤）

#### Scenario: 写代码让框架产出该文件放行

- **WHEN** tasks.md 含任务行提到 `test_scenarios.json`，但同时含代码文件路径（如 `core/agent_runner/prompt_builder.py`）
- **THEN** `lint_tasks_text` 对该任务行不返回违规

#### Scenario: 与验证产物无关的任务放行

- **WHEN** tasks.md 任务行既不引用验证产物路径、也不含任何代码文件
- **THEN** 该行不产生产物归属违规

### Requirement: 执行车道与归属比对

产物归属校验 SHALL 按 `.spec.yaml` 的 `mode` 判定本次执行车道，并与归属表比对：执行车道不在该产物的归属车道集合内 → 判违规。

`mode` 缺失或不可解析时 MUST 保守按 `full`（执行车道 = `implementer`）处理；`mode: fast-track` 时执行车道 = `fast-track`。

注：因归属表中「验证链产物」均不含 `implementer`，full 车道下「要求实现者产出验证产物」恒判违规；fast-track 车道下对 `test_scenarios.json`/`scenarios.json` 合法（fast-track 自行出题并落盘），对 `report.json`/`planner-judge` 结果文件仍判违规。

#### Scenario: full 车道要求产出验证产物判违规

- **WHEN** 某 spec（`.spec.yaml` 无 mode 行）的 tasks.md 任务行要求把场景集持久化到 `.fenix/verify-progress/<spec>/`
- **THEN** 判定执行车道为 `implementer`，归属表登记的场景集归属车道不含 `implementer`
- **AND** 判违规拒绝晋升

#### Scenario: fast-track 车道自行出题落盘合法

- **WHEN** 某 spec 的 `.spec.yaml` 为 `mode: fast-track`，tasks.md 任务行要求生成并落盘 `test_scenarios.json`（行内无代码文件引用）
- **THEN** 执行车道 `fast-track` 属该产物归属集合
- **AND** 不产生归属违规

#### Scenario: mode 缺失保守按 full

- **WHEN** spec 目录无可解析的 `.spec.yaml` mode 行
- **THEN** 执行车道按 `implementer` 处理（保守侧）

### Requirement: 三个 lint 挂点一致生效

产物归属校验 SHALL 复用 `lint_tasks_text` 单一实现，使以下三个挂点自动获得同一判定：晋升门 `drafted → ready`、full 车道 tasks.md 收口复检（`_tasks_md_relint_from_branch`）、fast-track 车道 tasks.md 收口复检（`_tasks_md_relint_from_worktree`）。

三个挂点 MUST NOT 各自实现一套判据。

#### Scenario: 晋升门拦截

- **WHEN** 某 drafted spec 的 tasks.md 含「要求实现者产出他车道验证产物」的任务行，daemon 执行晋升
- **THEN** 晋升 lint 返回违规，spec 停留 `drafted` 且 STATE error 含归属违规消息

#### Scenario: 收口复检同源

- **WHEN** 实现分支的 tasks.md（分支 HEAD 版本或 worktree 内版本）含同类违规任务行
- **THEN** `_tasks_md_relint_from_branch` / `_tasks_md_relint_from_worktree` 返回同一违规消息

### Requirement: 校验 fail-open 与零误拦

产物归属校验 SHALL 在自身故障时 fail-open（记 warning 返回空违规清单，不阻塞晋升/收口）；`mode` 读取异常 MUST 保守按 `full` 处理而非跳过校验。

规则 MUST 通过存量回归验证零误拦：对 `spec/changes/` 与 `spec/archive/` 下的全部 tasks.md 运行判定，合法 spec 不得产生违规。

#### Scenario: 读取异常不阻断晋升

- **WHEN** `.spec.yaml` 读取抛异常或 mode 值非法
- **THEN** 按 `full` 车道继续判定，不因异常跳过校验、也不抛异常中断晋升

#### Scenario: 存量 tasks.md 零误拦

- **WHEN** 对全库（changes + archive）既有 tasks.md 运行 lint_tasks_text
- **THEN** 既有合法 spec 均不产生产物归属违规
