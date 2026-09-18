## Why

SPEC 立项时，任务书可能被写成「要求实现者产出**只有验证链车道才会生成**的产物」——这类任务在实现者交付时根本不存在对应文件（验证尚未运行），Agent 无法完成、无法勾选，只能**伪造一份**来满足任务门禁。2026-09-18 `fix-verify-serving-disk-reclaim` 事故即此形态：其任务 6.2「写 `.fenix-run-result.json`，并持久化场景集与结果到 `.fenix/verify-progress/<spec>/`」由 SPEC 起草阶段写入 tasks.md，实现 run 忠实执行、用 Bash heredoc 伪造 23 条 `{id,spec,status,desc}` 的证据文案当 `test_scenarios.json`，验证链读侧见文件即当冻结场景集加载、验收报 23 个错误 → spec 被置 `blocked`（场景计划争议）。

现有 `skills/fenix-new/SKILL.md` §3.2.1 已禁止四类「Agent 做不到的事」（需人工运维门控 / 外部资源 / 人工裁决 / 主树专属写操作），但**未覆盖「需产出他车道产物」这一类**——起草者与 lint 都无据可依，事故因此漏出。堵写文件不可行（实现者持有 bash 全集，能绕过任何写侧 hook），根治点在**立项侧**：任何要求实现者产出他车道产物的任务，都必须在晋升前机械拦下，逼其改写成「实现 X 让框架产出该文件」。

## What Changes

- **新增产物归属表（单一真相源）**：声明式定义每个验证链产物由哪个车道产出（`test_scenarios.json` → planner-plan；`scenarios.json` → pm_engine；`report.json` → verify_engine；`planner-judge` 结果文件 → planner-judge；worktree 根 `.fenix-run-result.json` → implementer/fast-track）。
- **新增晋升 lint 规则**：`lint_tasks_text` 扫描 tasks.md 任务行，命中「任务要求产出验证链产物」且**未指向任何代码文件** → 判违规拒绝晋升；违规文案给出纠正处方。执行车道由 `.spec.yaml` 的 `mode` 决定，与归属表比对：**执行车道 ∉ 归属车道 → 拒绝**。
- **三个强制点自动生效**（`lint_tasks_text` 单实现）：晋升门 `drafted→ready`、full 车道收口 relint、fast-track 车道收口 relint。
- **起草指引同步**：`skills/fenix-new/SKILL.md` §3.2.1 的四类表格补第 5 类「需产出他车道产物」；`agents/evolution.md` 自进化起草 prompt 同步（两条起草入口都不漏）。
- 判据为文本层启发式、fail-open 取向：宁可漏拦怪题，绝不误拦合法 spec（全库 184 份 tasks.md 实测候选违规 0、真阳性 1）。

## Capabilities

### New Capabilities

- `task-artifact-ownership-gate`: tasks.md 任务行的「产物归属」机械校验——验证链产物归属表、执行车道判定、违规识别与纠正处方、三个 lint 挂点的一致语义、fail-open 边界。

### Modified Capabilities

<!-- 无：lint_tasks_text 的可解析性判定与 declaration-premechanize 的声明段软化
     是不同判定维度，本次在 lint_tasks_text 内新增独立规则，不修改其既有 Requirement。 -->

## Impact

- **代码**：`core/deliverables.py`（`lint_tasks_text` 新增规则 + 产物归属表常量）、可能新增 `core/artifact_ownership.py`（单一真相源，供 lint 与起草自检共用）。
- **提示词/文档**：`skills/fenix-new/SKILL.md`（§3.2.1 第 5 类）、`agents/evolution.md`（自进化起草格式契约）。
- **测试**：`tests/test_deliverables.py`（或新建 `tests/test_task_artifact_ownership.py`）——判据矩阵、车道比对、零误拦回归。
- **风险**：晋升门是全库 spec 的公共链路，误拦会阻断正常立项。缓解：规则要求「命中产物路径」**且**「未指向代码文件」双条件，且对 `.spec.yaml` mode 缺失保守按 full；必须用存量 184 份 tasks.md 做零误拦回归。
