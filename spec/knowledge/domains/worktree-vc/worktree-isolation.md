<!-- knowledge: capability=worktree-isolation rev=1 sources=spec/archive/2026-09-02-fix-worktree-agent-cwd -->

# worktree 隔离（Popen cwd 隔离）

实现工作在独立 git worktree 内进行：implementer 子进程的 cwd 指向 worktree，主树不被实现期改动污染，完成后经 merge-back 合入主树。

## 现行规则

- cwd 隔离：implementer 的 claude 子进程以 worktree 目录作为工作目录（cwd）运行——`agent_runner._run_claude` 的 `subprocess.Popen` 传入 `cwd=<worktree 路径>`；实现者的所有相对路径文件编辑（Read/Edit/Write）与 git commit 全部落在该 worktree（如 `.claude/worktrees/impl-<spec>-<ts>`），运行记录 init 事件的 `cwd` 等于 worktree 路径。运行期间主树保持干净（无该 SPEC 相关的未提交改动）。
- 成功后合并回主树：implementer 成功运行后将 worktree 分支（`fenix/<spec>-<ts>`）合并回主树，使用保留历史的 `git merge --no-ff`（或等价机制），具备幂等性（分支已为主树 HEAD 祖先时再次触发合并幂等跳过，不产生新 merge commit 或报错）。合并失败（如冲突）将 SPEC 标记为 error、不推进 `implemented`，STATE.md error 记录冲突详情，由既有重试机制重建 worktree 重做。
- tasks.md 读取路径与实际工作目录一致：`data.parse_tasks` 在 `implementing` 状态读取 worktree 的 tasks.md（实现者实时勾选处），merge-back 完成后的状态（implemented/testing/done）读取主树的 tasks.md（合并带回的勾选状态）。Dashboard 任务进度在任意生命周期状态反映实现者标记的完成状态（run 记录实时叠加与 tasks.md 勾选的并集）。
- 验证管线衔接：verifier 在主树运行并验证 merge 后的实现；implement → merge → verify 周期正常闭合（实现成功 → 合并回主树 → 主树验证 → 推进 verified/done）。

## 溯源

- 史前复原（存量基线） — 实现工作在独立 git worktree 内进行，主树不被实现期改动污染；完成后经 merge-back 合入主树
- [2026-09-02 fix-worktree-agent-cwd](spec/archive/2026-09-02-fix-worktree-agent-cwd/) — 固化 Popen cwd 指向 worktree、merge-back `--no-ff` 幂等合回、tasks.md 读取路径按生命周期分流与 implement→verify 周期不回归
