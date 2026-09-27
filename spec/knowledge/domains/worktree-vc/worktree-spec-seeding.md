<!-- knowledge: capability=worktree-spec-seeding rev=1 sources=spec/archive/2026-09-02-fix-worktree-spec-seeding -->

# worktree SPEC 播种

worktree 创建时把 SPEC 上下文（spec 目录与任务清单）播种进隔离分支，使 implementer 在 worktree 内直接可做，无需依赖主树未提交内容。

## 现行规则

- 条件播种：`core/worktree_manager.py::create` 完成 `git worktree add` 后，检查目标 SPEC 的 `spec/changes/<spec>/`——该目录在主工作树（项目根）存在、而在新建 worktree 内不存在（即分支 HEAD 未包含该 SPEC）时，将 SPEC 目录（proposal.md / design.md / specs/ / tasks.md 等）复制进 worktree，并提交到该隔离分支（提交信息格式 `[fenix] spec: <spec-name>`），分支由此自包含。SPEC 目录在主工作树不存在、或 worktree 内已存在（分支已含）时不执行播种（不产生额外 SPEC 提交、不复制文件）。
- 播种失败不阻塞创建：复制或提交 SPEC 文件发生异常时记录日志并继续，worktree 仍返回给调用方，实现 Agent 仍可用主仓库兜底路径。
- 实现变更归属隔离分支：播种后，实现 Agent 在 worktree 内修改/新增的文件（包括 tasks.md 勾选状态与 `.fenix-run-result.json`）归属于该隔离分支的工作区，不进入 `main` 分支工作树——worktree 与主工作树是两个独立 git 工作区，播种只把 SPEC 文件带入 worktree；实现期间 main 工作树的 `git status` 不含该 SPEC 的实现改动。

## 溯源

- 史前复原（存量基线） — worktree 创建时播种 SPEC 上下文（spec 目录与任务清单），implementer 在 worktree 内直接可做；Popen 须显式传 worktree cwd
- 2026-09-02 fix-worktree-spec-seeding — 固化条件播种语义（分支未含才播、`[fenix] spec:` 提交）、播种失败不阻塞创建、实现变更归属隔离分支不污染主工作树
