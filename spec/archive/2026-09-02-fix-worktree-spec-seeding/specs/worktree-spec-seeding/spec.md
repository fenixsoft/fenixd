## ADDED Requirements

### Requirement: 实现 worktree 播种 SPEC 源文件
`core/worktree_manager.py::create` 在完成 `git worktree add` 后，MUST 检查目标 SPEC 的 `spec/changes/<spec>/` 目录：若该目录在主工作树（项目根）存在，而在新建 worktree 内不存在（即分支 HEAD 未包含该 SPEC），则 MUST 将 SPEC 目录（proposal.md / design.md / specs/ / tasks.md 等）复制进 worktree，并将这些文件提交到该隔离分支（提交信息格式 `[fenix] spec: <spec-name>`）。若 SPEC 目录在主工作树不存在，或 worktree 内已存在（分支已含），则 MUST 不执行播种。播种过程失败 MUST 不阻塞 worktree 创建流程（记录日志并继续，实现 Agent 仍可用主仓库兜底路径）。

#### Scenario: 未提交的 SPEC 被播种进 worktree
- **WHEN** 某 SPEC 的 `spec/changes/<spec>/` 只存在于主工作树（未提交），且为其创建实现 worktree
- **THEN** worktree 内出现完整的 `spec/changes/<spec>/`，且该隔离分支多出一个 `[fenix] spec: <spec-name>` 提交，分支由此自包含

#### Scenario: 分支已含 SPEC 时不重复播种
- **WHEN** worktree 所在分支已包含 `spec/changes/<spec>/`
- **THEN** 不产生额外的 SPEC 提交，不复制文件

#### Scenario: 播种失败不阻塞创建
- **WHEN** 复制或提交 SPEC 文件时发生异常
- **THEN** 创建流程继续、worktree 仍返回给调用方，异常被记录到日志

### Requirement: 实现 Agent 变更落在隔离分支
播种后，实现 Agent 在 worktree 内工作所修改/新增的文件（包括 tasks.md 勾选状态与 `.fenix-run-result.json`）MUST 归属于该隔离分支的工作区，不进入 `main` 分支工作树。即：实现 Agent 的 cwd（worktree）与主工作树是两个独立 git 工作区，播种只把 SPEC 文件带入 worktree，不改变实现 Agent 的主工作树。

#### Scenario: 实现期间 main 工作树不被污染
- **WHEN** 实现 Agent 完成 SPEC 播种后的实现工作并在 worktree 内提交
- **THEN** `main` 分支工作树的 `git status` 不包含该 SPEC 的实现改动（该改动仅存在于隔离分支）
