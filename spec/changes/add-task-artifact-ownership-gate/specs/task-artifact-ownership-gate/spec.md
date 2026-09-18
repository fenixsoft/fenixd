# Spec: task-artifact-ownership-gate

## ADDED Requirements

### Requirement: 验证产物归属表

框架 SHALL 维护一份声明式的「验证链产物 → 归属车道」归属表作为单一真相源，供 lint 侧与起草自检侧共用，避免多处枚举漂移。

归属表至少 MUST 覆盖以下产物与归属：

- `.fenix/verify-progress/<spec>/test_scenarios.json` → 归属 `planner-plan`（`fast-track` 亦为合法产出车道）
- `.fenix/verify-progress/<spec>/scenarios.json` → 归属 pm_engine 持久化写侧（`fast-track` 亦为合法产出车道）
- `.fenix/verify-progress/<spec>/report.json` → 归属 `verify_engine`
- `.fenix/verify-progress/<spec>/.fenix-run-result.json` → 归属 `planner-judge`
- `.fenix/verify-progress/<spec>/`（目录级持久化引用）→ 归属 `planner-plan` / `pm_engine` / `verify_engine` / `planner-judge` / `fast-track`
- `<worktree>/.fenix-run-result.json` → 归属 `implementer` / `fast-track`（实现者自己的收工票据，合法交付）

`implementer` 车道 MUST NOT 被登记为上述任一验证链产物的归属车道。未登记到本表的侧车文件（如 `tokens.json`、`fail_history.json`、`warning_streaks.json`）MUST NOT 参与违规判定。

#### Scenario: 归属表覆盖核心验证产物

- **WHEN** 代码加载归属表
- **THEN** 表中含 `test_scenarios.json`/`scenarios.json`/`report.json`/`planner-judge` 结果文件四条验证链产物条目
- **AND** 每条条目的归属车道集合中不含 `implementer`

### Requirement: 任务行产物归属校验

`lint_tasks_text` SHALL 在 tasks.md 可解析性判定之外，额外对每条任务行执行「产物归属」校验：命中**已登记验证链产物的产出式引用**，且该任务行**未指向任何代码文件**，且该产物的归属车道集合不含本次执行车道时判违规。

判据 MUST 同时满足三个条件才判违规（零误拦取向）：

1. 任务行命中**已登记的验证链产物引用**——引用 MUST 路径限定到 `.fenix/verify-progress/…` **且**为归属表登记的核心产物之一（`test_scenarios.json` / `scenarios.json` / `report.json` / `<vp_dir>/.fenix-run-result.json`），**或**为 `.fenix/verify-progress/<spec>/` 目录自身的持久化引用；
2. 该引用处**未指向任何代码文件**——把命中的产物字面量遮蔽后，行内不出现代码扩展名（`.py`/`.ts`/`.tsx`/`.js`/`.jsx`/`.sh`/`.yaml`/`.yml`）或已知代码路径特征（`core/`、`agents/`、`tests/`、`bin/`、`skills/`、`docs/`）；
3. 引用前出现产出动词（写 / 落盘 / 持久化 / 保存 / 落位 / 序列化 / 追加），且执行车道 ∉ 该产物归属车道集合（见「执行车道与归属比对」）。

仅命中其一 MUST NOT 判违规——以下合法形态必须放行：

- 「写代码让框架产出该文件」的任务（如「新增 `_write_impl_result_snapshot` 落盘快照到 verify-progress」）；
- **裸** `test_scenarios.json`/`scenarios.json`/`report.json` 字面量引用——`specs/scenarios.json` 指 spec 目录下的场景定义件，与 `.fenix/verify-progress/<spec>/scenarios.json` 为不同文件；「旧格式 report.json 兼容解析」等为读取/兼容语义；
- **裸** `.fenix-run-result.json`——实现者/fast-track 自己的收工票据（归属表的合法交付项，`agents/implementer.md` 第 7 步 MUST 写）；
- 未登记到归属表的侧车产物（`tokens.json`/`fail_history.json`/`warning_streaks.json`/`baseline_streaks.json` 等）——它们由实现者自行落盘，是合法交付。

#### Scenario: 要求实现者持久化他车道产物判违规

- **WHEN** tasks.md 含任务行 `- [ ] 6.2 写 .fenix-run-result.json，并持久化场景集与结果到 .fenix/verify-progress/<spec>/`（行内无任何代码文件引用）
- **THEN** `lint_tasks_text` 返回违规，消息点名该任务行 id 与所命中的验证产物路径
- **AND** 违规消息给出纠正处方：改写为「实现 X 让框架产出该文件」或移出任务书（reference / `.fenix/todo.md` 人工步骤）

#### Scenario: 裸产物字面量引用放行

- **WHEN** tasks.md 含任务行 `spec 戳计算：spec/changes/<spec>/spec.md 与 specs/scenarios.json 内容 sha256 前 16 位`
- **THEN** 该引用非路径限定到 `.fenix/verify-progress/`，不判违规

#### Scenario: 实现者写自己的收工票据放行

- **WHEN** tasks.md 含任务行 `写 .fenix-run-result.json（含 completed_tasks）`（无 verify-progress 目录引用）
- **THEN** 不判违规——worktree 根结果文件的归属车道含 `implementer`/`fast-track`

#### Scenario: 未登记侧车放行

- **WHEN** tasks.md 含任务行 `门入口把 {"round": …} 写入 .fenix/verify-progress/<spec>/scenario_reroute_stoploss.json`
- **THEN** 该文件未登记到归属表，不判违规

#### Scenario: 写代码让框架产出该文件放行

- **WHEN** tasks.md 含任务行提到 `test_scenarios.json`，但同时含代码文件路径（如 `core/agent_runner/prompt_builder.py`）
- **THEN** `lint_tasks_text` 对该任务行不返回违规

#### Scenario: 与验证产物无关的任务放行

- **WHEN** tasks.md 任务行既不引用验证产物路径、也不含任何代码文件
- **THEN** 该行不产生产物归属违规

### Requirement: 执行车道与归属比对

产物归属校验 SHALL 按 `.spec.yaml` 的 `mode` 判定本次执行车道，并与归属表比对：执行车道不在该产物的归属车道集合内 → 判违规。

`mode` 缺失或不可解析时 MUST 保守按 `full`（执行车道 = `implementer`）处理；`mode: fast-track` 时执行车道 = `fast-track`。车道读取 SHALL 复用既有 `core/spec_mode.py:read_spec_mode`（同一 `.spec.yaml` `mode` 读取器，读侧容错语义一致：缺失/非法/解析失败一律返回 `full`），MUST NOT 自实现第二套 YAML 解析。

注：因归属表中「验证链产物」均不含 `implementer`，full 车道下「要求实现者产出验证产物」恒判违规；fast-track 车道下对 `test_scenarios.json`/`scenarios.json` 合法（fast-track 自行出题并落盘），对 `report.json`/`planner-judge` 结果文件仍判违规。

**注（自进化草稿入口的车道语义）**：`evo-*` 自进化草稿由 `core/evolution.py`（`SPEC_YAML_TEMPLATE`）落盘为固定 `mode: full`，其草稿 lint 预检（`lint_draft`）亦按 full 判定。该规则对自进化入口因此为**不可达**（非误拦、非漏拦，属草稿模板既有约束）；本 SPEC 不改变该模板。

#### Scenario: full 车道要求产出验证产物判违规

- **WHEN** 某 spec（`.spec.yaml` 无 mode 行）的 tasks.md 任务行要求把场景集持久化到 `.fenix/verify-progress/<spec>/`
- **THEN** 判定执行车道为 `implementer`，归属表登记的场景集归属车道不含 `implementer`
- **AND** 判违规拒绝晋升

#### Scenario: fast-track 车道自行出题落盘合法

- **WHEN** 某 spec 的 `.spec.yaml` 为 `mode: fast-track`，tasks.md 任务行要求生成并落盘 `test_scenarios.json` 到 `.fenix/verify-progress/<spec>/`（行内无代码文件引用）
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

规则 MUST 通过存量回归验证零误拦：对 `spec/changes/` 与 `spec/archive/` 下的全部 tasks.md 运行判定，合法 spec 不得产生违规。回归基线为实测的 260 份 tasks.md（`spec/changes` 61 + `spec/archive` 199）/ 3424 条任务行，唯一预期违规为 `spec/changes/fix-verify-serving-disk-reclaim/tasks.md:76`（事故真阳性，实现期可通过重写该任务行使其转为零违规，测试内 MUST NOT 硬编码文件数或该条断言）。

#### Scenario: 读取异常不阻断晋升

- **WHEN** `.spec.yaml` 读取抛异常或 mode 值非法
- **THEN** 按 `full` 车道继续判定，不因异常跳过校验、也不抛异常中断晋升

#### Scenario: 存量 tasks.md 零误拦

- **WHEN** 对全库（changes + archive）既有 tasks.md 运行 lint_tasks_text
- **THEN** 既有合法 spec 均不产生产物归属违规（含「裸 report.json/scenarios.json 引用」「实现者写自己的 `.fenix-run-result.json` 收工票据」「写入未登记侧车」「spec 目录下 specs/scenarios.json 引用」四类已知合法形态）
