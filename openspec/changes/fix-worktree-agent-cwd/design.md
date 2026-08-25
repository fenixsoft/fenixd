# Design: 修复 implementer 未在 worktree 隔离工作

## Context

当前实现链路（`fenixd.py` → `PMEngine._run_agent_worker` → `AgentRunner.run_implementer` → `_execute_agent` → `_run_claude` → `claude` CLI 子进程）：

- `_execute_agent` 先调用 `worktree_manager.create(spec_name, "implementer")` 创建 worktree（分支 `fenix/<spec>-<ts>`，目录 `.claude/worktrees/impl-<spec>-<ts>/`），并把 `spec_name` 的 SPEC 目录 seed 进 worktree。
- 然后 `_run_claude(prompt, wt_path, run_id, ...)` —— `wt_path` 即 worktree 路径。
- `_run_claude` 构造命令时把 `wt_path` 经 `--add-dir` 加入会话，但 **`subprocess.Popen(...)` 未传 `cwd=`**，子进程继承 daemon 的 cwd（项目主树）。
- 因此 prompt 的相对路径（`openspec/changes/<spec>/...`、`.fenix-run-result.json`）全部解析到主树；实现者的编辑、git commit 直接落在 main；worktree 始终 clean。
- 运行结束后 `worktree_manager.cleanup(wt_path, success=...)` 仅移除 worktree（`git worktree remove`），**无任何合并回主树的步骤**。

次级影响：
- `data.parse_tasks` 对 `implementing` 状态经 `find_implementer_worktree` 读 worktree 的 tasks.md（stale）。
- verifier 管线（`pm_engine._run_three_stage_verification`）的 `VerifyEngine(spec_name, project_root, ...)` 与 prompt 均相对主树运行。

## Goals / Non-Goals

**Goals:**
- implementer 的 claude 子进程 cwd = worktree 路径，编辑与提交全部落在 worktree。
- 实现成功后，worktree 分支合并回主树，主树包含可供 verifier 验证的实现。
- `data.parse_tasks` / `find_implementer_worktree` 读取位置与 tasks.md 实际所在一致。
- 回归：全量单元测试通过；一次完整 implement→verify 周期正常。

**Non-Goals:**
- 不改变实时任务进度叠加（`data.parse_tasks` 的 run 记录 overlay，独立已实现）。
- 不重构 verifier 的验证引擎本身（仅核对路径假设）。
- 不引入 merge 冲突的自动解决策略（冲突时标记 error、不推进状态，交由重试/人工）。

## Decisions

### D1: `_run_claude` 向 `Popen` 传入 `cwd=worktree 路径`

`core/agent_runner.py::_run_claude`：

```python
proc = subprocess.Popen(
    cmd,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    bufsize=1,
    env=env,
    cwd=str(cwd),          # ← 新增：让 implementer 真正在 worktree 中工作
)
```

- `--add-dir <worktree>` 可保留（双保险），但 cwd 才是决定相对路径解析的关键。
- 验证：运行中 run 记录的 init 事件 `cwd` 应等于 worktree 路径；worktree `git status` 出现实现者编辑，主树保持干净。

### D2: 成功后 merge-back worktree 分支回主树

在 `pm_engine._run_agent_worker` 的 implementer 成功路径（当前 `state_machine.transition(spec_name, "implemented")` 之前），新增「把 worktree 分支合并回主树」步骤：

```python
# 伪代码：成功后、推进状态前
branch = f"{prefix}/{spec_name}-{timestamp}"   # 与 worktree_manager.create 生成的分支名一致
merged = git_merge_worktree_branch(self.project_root, branch)   # git merge --no-ff <branch>（在主树执行）
if not merged:
    # 合并失败（冲突等）→ 标记 error，不推进 implemented，保留可重试状态
```

- 分支名需与 `worktree_manager.create`（`fenix/<spec>-<ts>`）保持一致 —— 建议 `worktree_manager` 暴露「当前活动 worktree 的分支名」查询，避免硬编码耦合。
- `git merge --no-ff` 保留 worktree 分支历史，便于审计。
- 合并应在主树当前 HEAD 上进行；若主树有未提交改动导致冲突，需在合并前妥善处理（或要求主树 clean —— 修复后实现者不再直接编辑主树，主树应保持干净）。
- 合并成功后：verifier 在主树验证的是合并后的代码；`git log` 可见 merge commit。

### D3: 对齐读取路径

- `core/dashboard/data.py::parse_tasks`：`implementing` 状态仍经 `find_implementer_worktree` 读 worktree tasks.md（这是实现者实际工作目录，修复后正确）；`implemented`/后续状态在 merge-back 后读主树 tasks.md（merge 已把勾选状态带回主树）。需核对 `spec_status` 分支逻辑。
- `worktree_manager.find_implementer_worktree`：按 mtime 取最新 `impl-<spec>-*`，修复后语义成立（worktree 真正承载实现者编辑）。
- `pm_engine._read_implementer_result`：已 worktree 优先、主树回退，维持不变；merge-back 成功后主树也应存在 `.fenix-run-result.json`（随 merge 带回）或由读回逻辑优先 worktree（运行中）。
- verifier 的 `verify-progress` / `spec_dir` 相对主树，与 merge-back 后的主树一致，无需改动。

### D4: 失败回退与幂等

- merge 失败：更新 STATE.md `error`（含冲突详情），**不** `transition("implemented")`；`_execute_agent` 的 retry 机制自然重试（worktree 移除、重建）。
- merge 成功但后续验证失败：正常走 bug-found 流程，无需特殊处理。
- 幂等：merge 前检查分支是否已合并（`git merge-base --is-ancestor`），避免重复 merge。

## Open Questions

- merge-back 的归属：放在 `pm_engine`（状态推进前）还是 `agent_runner._execute_agent`（运行结束清理前）？倾向 pm_engine —— 状态机事务边界清晰，且 worktree_manager 只负责 worktree 生命周期。
- 主树未提交改动与 merge 冲突的处理策略（是否要求主树 clean / stash）。

## 测试计划

- 单元测试：`_run_claude` 的 `Popen` 收到 `cwd=worktree`（mock Popen 断言参数）；merge-back 函数在成功/冲突/已合并三种情况的行为。
- 集成：`data.parse_tasks` 在 `implementing`（读 worktree）与 `implemented`（读主树）两态下读取位置正确。
- 回归：`python3 -m pytest tests/ -q` 全量通过；端到端跑一个 implement→verify 周期，确认 worktree 隔离生效、merge 后主树含实现、Dashboard 任务进度正常。
