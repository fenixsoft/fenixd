## ADDED Requirements

### Requirement: Implementer 在独立 worktree 中隔离实现

系统 SHALL 让 implementer 的 claude 子进程以 **worktree 目录作为工作目录（cwd）** 运行，使实现者的所有相对路径文件编辑与 git commit 落在该 worktree 内，而非项目主树。运行期间主树 SHALL 保持干净（不出现实现者的未提交改动）。`agent_runner._run_claude` 的 `subprocess.Popen` SHALL 传入 `cwd=<worktree 路径>`。

#### Scenario: 运行中 implementer 的 cwd 指向 worktree

- **WHEN** daemon 调度 implementer 运行 SPEC `s`，创建 worktree `impl-s-<ts>` 后启动 claude 子进程
- **THEN** 该子进程的运行记录 init 事件 `cwd` SHALL 等于 worktree 路径 `.claude/worktrees/impl-s-<ts>`；实现者执行的 `Read`/`Edit`/`Write`/git 操作均落在该 worktree

#### Scenario: 主树在运行期间保持干净

- **WHEN** implementer 在 worktree 中完成编辑与提交
- **THEN** 主树的 `git status` SHALL 无该 SPEC 相关的未提交改动；worktree 的 `git status` SHALL 含实现者新增的提交

### Requirement: 成功后 worktree 分支合并回主树

系统 SHALL 在 implementer 成功运行后，将 worktree 分支（`fenix/<spec>-<ts>`）合并回主树，确保主树包含实现供 verifier 验证。合并 SHALL 使用保留历史的 `git merge --no-ff`（或等价机制），且 SHALL 具备幂等性（已合并的分支不重复合并）。合并失败（如冲突）SHALL 将 SPEC 标记为 error、不推进到 `implemented`，并可由现有重试机制重建 worktree 重试。

#### Scenario: 实现成功后主树包含合并后的实现

- **WHEN** implementer 运行成功（worktree 分支含实现提交），merge-back 执行
- **THEN** 主树 `git log` SHALL 出现该实现提交（或包含它的 merge commit），`git merge-base --is-ancestor <branch> HEAD` 成立；SPEC 随后正常推进 `implemented` 并排队 verifier

#### Scenario: merge 冲突时不推进状态

- **WHEN** merge-back 因主树存在冲突/未提交改动而失败
- **THEN** SPEC 状态 SHALL 保持可重试（不进入 `implemented`），STATE.md `error` SHALL 记录冲突详情；重试后重建 worktree 重新实现

#### Scenario: 已合并的分支不重复合并

- **WHEN** merge-back 已被执行过（分支已是主树 HEAD 祖先）
- **THEN** 再次触发 merge SHALL 幂等跳过，不产生新的 merge commit 或报错

### Requirement: tasks.md 读取路径与实际工作目录一致

系统 SHALL 确保 `data.parse_tasks` 读取的 tasks.md 与实现者实际编辑的位置一致：`implementing` 状态读取 worktree 的 tasks.md（实现者实时勾选处），merge-back 完成后的状态读取主树的 tasks.md（合并带回的勾选状态）。Dashboard 任务进度 SHALL 在任意生命周期状态反映实现者标记的完成状态（含实时叠加 run 记录与 tasks.md 勾选的并集）。

#### Scenario: implementing 期间 Dashboard 显示 worktree tasks.md 勾选

- **WHEN** 实现者在 worktree 中把 `tasks.md` 的任务 `- [ ]` 改为 `- [x]`
- **THEN** `data.parse_tasks(spec, "implementing")` SHALL 返回含该勾选的进度，Dashboard「任务清单」实时更新

#### Scenario: merge 后 Dashboard 读取主树 tasks.md

- **WHEN** 实现成功、merge-back 完成、SPEC 状态为 `implemented`/`testing`/`done`
- **THEN** `data.parse_tasks(spec, 该状态)` SHALL 从主树 tasks.md 读取（merge 已带回勾选），进度与实现者标记一致

### Requirement: 回归与验证管线不回归

系统 SHALL 在修复后保持既有验证管线可用：verifier 在主树运行并验证 merge 后的实现；`python3 -m pytest tests/ -q` 全量通过；一次完整 implement→verify 周期正常结束（实现 → 合并 → 验证 → 结果判定）。

#### Scenario: 完整 implement→verify 周期正常

- **WHEN** 在真实项目上运行一个完整实现与验证周期
- **THEN** implementer 在 worktree 实现 → 成功后 merge 回主树 → verifier 在主树验证合并后的代码 → 正常推进 `verified`/`done`，无回归

#### Scenario: 全量单元测试通过

- **WHEN** 执行 `python3 -m pytest tests/ -q`
- **THEN** 全部用例通过（含新增的 cwd 传入、merge-back、读取路径对齐用例），无既有用例回归
