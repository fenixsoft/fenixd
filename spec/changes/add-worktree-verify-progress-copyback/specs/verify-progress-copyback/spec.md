# verify-progress-copyback 能力规范

## ADDED Requirements

### Requirement: worktree per-spec 验证产物成功收尾拷回

run 成功收尾时（runner 成功路径、worktree 清理之前），框架 SHALL 把 worktree 内
`.fenix/verify-progress/<spec>/` 目录的全部文件逐个拷回主树同路径
`<project_root>/.fenix/verify-progress/<spec>/`，使 agent 落在 worktree 真实
`.fenix/` 中的 per-spec 验证产物（`.fenix-run-result.json`、`test_scenarios.json`、
进度文件等）在 worktree 清理后仍可在主树被 Dashboard 读侧（场景结果页签、验证进度、
报告兜底链）读取。

#### Scenario: 产物仅在 worktree 时拷回主树

- **WHEN** run 成功收尾且主树 `<project_root>/.fenix/verify-progress/<spec>/` 缺少
  worktree 内存在的文件（如 `.fenix-run-result.json`）
- **THEN** 该文件被拷回主树同路径，内容与 worktree 版本逐字节一致
- **THEN** 拷回发生在该 worktree 的清理（`cleanup` / 延迟清理）之前

#### Scenario: 主树已有所需文件时行为

- **WHEN** run 成功收尾且 worktree 产物文件在主树同路径已存在
  - 若 worktree 版本 mtime 较新 → 覆盖主树文件（mtime 保留为 worktree 版本的 mtime）
  - 若主树版本 mtime 较新（含 worktree 复用继承的陈旧产物场景）→ 不拷贝、保留主树版本
- **THEN** 主树独有的文件（如 full 模式 planner 直写的冻结场景集、`impl-result.json`
  快照、`warning_streaks.json` 等框架簿记）一律不被删除、不被陈旧版本覆盖

### Requirement: 拷回失败不阻塞 run 终态

拷回过程 SHALL fail-open：任何 OSError（源不可读、目标不可写、目录创建失败等）
仅记 WARNING 日志（含 spec 名与失败路径），不得抛出、不得阻断 run 成功终态、
状态机推进与 worktree 清理。

#### Scenario: 拷贝异常时 run 照常收工

- **WHEN** 拷回过程中任一文件读写失败（OSError）
- **THEN** 框架记录一条 WARNING 日志
- **THEN** run 的成功终态、后续状态推进与 worktree 清理不受影响（既有共享文件
  `.fenix-run-result.json` 的拷贝行为同时保持不变）

### Requirement: 无产物目录时零行为

worktree 内不存在 `.fenix/verify-progress/<spec>/` 目录时（agent 全部走主树绝对路径
写入的正常形态），拷回步骤 SHALL 零动作、零日志噪音，不创建空目录。

#### Scenario: worktree 无产物目录

- **WHEN** run 成功收尾且 worktree 内无 `.fenix/verify-progress/<spec>/` 目录
- **THEN** 主树对应目录不被创建、既有内容不变，行为与修复前逐字节一致
