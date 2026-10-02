## Deliverables

```yaml
- path: core/git_base_branch.py
  kind: new
- path: core/state_machine.py
  kind: modify
- path: core/worktree_manager/queries.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: core/pm_engine/verification/branch_guard.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: tests/test_git_base_branch.py
  kind: new
- path: tests/test_recovery_branch_anchor.py
  kind: modify
```

## 1. 共享基线分支解析器

- [x] 1.1 core/git_base_branch.py：新建模块，实现 `resolve_base_branch(project_root, timeout: float = 15.0) -> str`——解析顺序 `git symbolic-ref --short refs/remotes/origin/HEAD`（去 `origin/` 前缀）→ `git rev-parse --verify --quiet main` → 同法探 master → 回退 `"main"`；子进程统一带 timeout、捕获 TimeoutExpired/OSError；按 project_root 提供进程内缓存（含显式 `reset_cache()` 供测试）；模块 docstring 记录决策来源（fenixd.py `_preserve_base_branch` / code-review item ec528621b2ec / 2026-10-02 potplayer-base 事故）；MUST NOT import fenixd。
- [x] 1.2 tests/test_git_base_branch.py：新建单测，用 tmp 目录真实 git 仓覆盖——仅 master 主干无 remote（返回 master）、main 主干（返回 main）、双主干（返回 main）、origin/HEAD 指向非 main 分支（返回该分支名）、非 git 目录（返回 "main" 不抛异常）、缓存命中（二次调用不再起子进程，以 monkeypatch 计数验证）。

## 2. 恢复续做判定接入

- [x] 2.1 core/state_machine.py `_resolve_preserved_branch`：将 rev-list 闸门（现 :2685 附近 `f"main..{branch}"`）的基线替换为 `resolve_base_branch(project_root)`；git 调用失败/超时的既有 (None, None) 早退语义与「三处锚点均不可得」WARNING 文案保持不变；同步修正函数 docstring 中「相对 main」表述为「相对解析基线」。
- [x] 2.2 tests/test_recovery_branch_anchor.py：新增 master 主干回归用例——tmp 仓 `git init` 后把分支改名为 master、无 main、无 remote，构造 spec 分支含 1 个未合并提交且 STATE.branch 缺失，断言 `_resolve_preserved_branch` 返回该分支、`_recovery_preserve_spec` 写入 `_recovery_resume: True` 与 branch、不触发「三处锚点均不可得」清空重建日志；再补一条「分支相对 master 零提交 → 仍走清空重建」的反例，锁死不误保留。

## 3. 分支命名空间枚举与待合并判定接入

- [x] 3.1 core/worktree_manager/queries.py：将 find_branches_by_spec 的候选 rev-list 剔除/排序（现 :579、:721）、同函数「已含基线」分组键 `git merge-base --is-ancestor main <branch>`（现 :562，master 主干仓库恒 False 致分组退化）、has_pending_merge / pending_merge_since 的 `git log -1 --format=%ct main..<branch>`（现 :745 附近）四处基线统一替换为 `resolve_base_branch(self.project_root)`；查询失败的 fail-closed 返回（空列表/None）语义不变。
- [x] 3.2 tests/test_recovery_branch_anchor.py：新增 master 主干下的 find_branches_by_spec 用例（worktree 已清、仅剩含 1 提交的实现分支 → 枚举命中该候选）与 pending_merge_since 用例（返回该分支最新提交的 committer date 而非 None），并断言 main 主干既有用例结果不变。

## 4. 终态零提交门与遗产快照接入

- [x] 4.1 core/agent_runner/runner.py `_check_terminal_no_commit_gate`：零提交判定的 rev-list（docstring 见 :1937-1946）基线替换为 `resolve_base_branch`；rev-list 或解析失败时维持现行 fail-open（放行并按既有口径留痕），门抛错契约（`[terminal-no-commit]` 前缀 AgentArtifactGateError）不变。
- [x] 4.2 core/agent_runner/prompt_builder.py legacy 提交快照（现 :1966 附近 `git log --oneline main..branch`）：基线替换为 `resolve_base_branch`，失败时维持现行降级（快照为空）语义，同步修正相关 docstring 与日志文案中的「main」表述。
- [x] 4.3 tests/test_git_base_branch.py：补两组调用点用例——master 主干仓中零提交+dirty 现场 `_check_terminal_no_commit_gate` 抛 `[terminal-no-commit]` 错误、有提交时不抛；legacy 快照在 master 主干仓返回提交清单而非空。

## 5. fenixd.py 收敛单源

- [x] 5.1 fenixd.py：`_preserve_base_branch` 改为委托 `core.git_base_branch.resolve_base_branch`（保留函数名、进程内缓存语义与 PRESERVE_AHEAD_BASE_BRANCH 兜底常量，`_ahead_commit_count` 及 :4703、:4868 两处调用点零改动），使无 remote 的 master 主干仓库 ahead 计数不再恒 0。
- [x] 5.2 tests/test_git_base_branch.py：补一条 `_ahead_commit_count` 级语义用例——master 主干无 remote 仓中含 1 提交的分支计数为 1（经 fenixd 侧公开路径或以同参调用共享解析器等价断言），并在 docstring 标注其对 `_preserve_interrupted_runs`/`_preserve_implementing_specs` 保全条目 ahead 字段的影响。

## 6. 零变更哨与验证分支守卫基线收敛

- [x] 6.1 core/pm_engine/verification/branch_guard.py `_branch_commit_count`：将 `baselines = ["main"]` 候选循环与 origin/HEAD 回落探测（现 :111-146）替换为经 `resolve_base_branch(project_root)` 解析的单基线（先解析后 rev-list 一次）；rev-list 失败仍返回 None、调用方 fail-open 语义不变；同步修正 docstring 中「回落仅发生在首候选非零退出后」段落为解析器口径。
- [x] 6.2 tests/test_git_base_branch.py：补 branch_guard 调用点用例——master 主干无 remote 仓中含 1 提交分支 `_branch_commit_count` 返回 1（非 None）、真零提交分支返回 0（零变更哨可判零变更）；main 主干既有用例结果不变。