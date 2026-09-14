# Proposal: add-worktree-verify-progress-copyback

## Why

fast-track run 的 per-spec 验证产物（`.fenix/verify-progress/<spec>/` 下的 `.fenix-run-result.json`、`test_scenarios.json` 等）可能落在 worktree 自己的真实 `.fenix/` 目录里（如 planner-scenario-batching hook deny 后 agent 绕道 Bash 相对路径写入），而 runner 成功路径只把 worktree 根部的 `.fenix-run-result.json` 拷回主树**共享文件**，per-spec 目录无拷回机制——worktree 清理即销毁，随后共享文件被下一 spec 覆盖，Dashboard「场景结果」页签数据永久蒸发。2026-09-09 双事故实证（add-verify-contract-autodraft-ui、fix-verify-cli-cwd-isolation，数据只能靠 run 转录手工恢复）。

## What Changes

- runner 成功收尾路径（`core/agent_runner/runner.py` 既有「worktree 根 result → 主树共享文件」拷贝点旁）新增：把 worktree 的 `.fenix/verify-progress/<spec>/` 整目录按文件拷回主树同路径。
- 拷贝语义：逐文件覆盖拷贝 + mtime 守卫——主树同路径文件缺失或 worktree 版本更新时才拷贝；防止 worktree 复用继承的陈旧产物覆盖主树较新文件（如 full 模式 planner 直写主树的冻结场景集）。
- 失败 fail-open：拷贝异常仅记 WARNING，不阻塞 run 终态主流程（与既有根 result 拷贝同风格）。

## Capabilities

### New Capabilities

- `verify-progress-copyback`：worktree 内 per-spec 验证产物目录的成功收尾拷回契约（拷贝范围、mtime 守卫、fail-open 语义）。

### Modified Capabilities

（无——既有能力不受影响；`.fenix-run-result.json` 根文件→共享文件的既有拷贝行为保持不变）

## Impact

- `core/agent_runner/runner.py`（成功路径新增目录拷回，约 20 行）
- `tests/test_verify_progress_copyback.py`（新增单测：拷回成功/陈旧守卫/主树独有文件保留/fail-open）
- 风险面：只增不改——既有共享文件拷贝、状态机推进、worktree 清理时序均不动；mtime 守卫保证不会用继承的陈旧产物污染主树冻结场景集。
