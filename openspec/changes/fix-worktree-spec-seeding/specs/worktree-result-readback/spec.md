## ADDED Requirements

### Requirement: 实现结果从活跃 implementer worktree 读取
`core/pm_engine.py` 读取实现 Agent 的结果（`.fenix-run-result.json`）时，MUST 优先从该 SPEC 的活跃 implementer worktree 读取：定位路径按 `impl-<spec>-*` 匹配的 worktree（存在多个时取最新的一个），若该 worktree 存在 `.fenix-run-result.json` 则读取之；否则回退项目根的 `.fenix-run-result.json`。本行为仅针对 implementer 结果读取；verifier / planner 的结果读取位置维持现状（项目根）。

#### Scenario: 结果在 worktree 时被正确读取
- **WHEN** SPEC 处于实现中，其活跃 worktree 内含 `.fenix-run-result.json`（如 status=success）
- **THEN** daemon 从该 worktree 读取到该结果并按现状语义处理（推进状态/重试/标记错误）

#### Scenario: worktree 缺失时回退项目根
- **WHEN** SPEC 无活跃 implementer worktree，但项目根存在 `.fenix-run-result.json`
- **THEN** daemon 按现状从项目根读取结果，行为不变

#### Scenario: verifier/planner 读取位置不变
- **WHEN** verifier 或 planner 运行并写 `.fenix-run-result.json` 于项目根
- **THEN** daemon 仍从项目根读取其结果，不受 worktree 优先逻辑影响

### Requirement: 任务进度展示从 worktree 读取（implementing 阶段）
`bin/statusline.py`、`core/dashboard/data.py` 与 `/fenix-status` skill 的任务进度解析，对状态为 `implementing` 的 SPEC MUST 优先从该 SPEC 的活跃 implementer worktree 的 `openspec/changes/<spec>/tasks.md` 读取勾选进度；worktree 不存在或文件缺失时回退主仓库 `openspec/changes/<spec>/tasks.md`。非 implementing 状态（testing / verified / done / bug-found 等）MUST 一律从主仓库读取。

#### Scenario: implementing 进度显示 worktree 勾选状态
- **WHEN** 某 SPEC 处于 implementing 且其 worktree 的 tasks.md 有 `- [x]` 勾选
- **THEN** 状态栏 / 仪表盘 / `/fenix-status` 显示该 worktree 中的已完成任务数与进度

#### Scenario: 非 implementing 阶段读主仓库
- **WHEN** 某 SPEC 处于 testing 或已完成（worktree 已清理），主仓库 tasks.md 有最终勾选状态
- **THEN** 进度展示读主仓库 tasks.md，显示最终进度
