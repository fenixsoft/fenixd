# 验证进度回传
<!-- knowledge: capability=verify-progress-copyback rev=1 sources=spec/archive/2026-09-14-add-worktree-verify-progress-copyback -->

worktree 内 per-spec 验证产物在 run 成功收尾时拷回主树：worktree 清理后 Dashboard 读侧仍可读。

## 现行规则

- 拷回时机与范围：run 成功收尾时（runner 成功路径、worktree 清理之前），把 worktree 内 `.fenix/verify-progress/<spec>/` 目录全部文件逐个拷回主树同路径 `<project_root>/.fenix/verify-progress/<spec>/`，使 agent 落在 worktree 真实 `.fenix/` 中的 per-spec 产物（`.fenix-run-result.json`、`test_scenarios.json`、进度文件等）在 worktree 清理后仍可被 Dashboard 读侧（场景结果页签、验证进度、报告兜底链）读取。
- mtime 冲突处理：worktree 版本较新 → 覆盖主树文件（mtime 保留为 worktree 版本的 mtime）；主树版本较新（含 worktree 复用继承的陈旧产物场景）→ 不拷贝、保留主树版本。主树独有文件（full 模式 planner 直写的冻结场景集、`impl-result.json` 快照、`warning_streaks.json` 等框架簿记）一律不删除、不被陈旧版本覆盖。
- fail-open：拷回过程任何 OSError（源不可读、目标不可写、目录创建失败等）仅记 WARNING 日志（含 spec 名与失败路径），不抛出、不阻断 run 成功终态、状态机推进与 worktree 清理。
- 零产物零行为：worktree 内不存在 `.fenix/verify-progress/<spec>/` 目录时（agent 全部走主树绝对路径写入的正常形态），拷回零动作、零日志噪音，不创建空目录。

## 溯源

- [2026-09-14 add-worktree-verify-progress-copyback](spec/archive/2026-09-14-add-worktree-verify-progress-copyback/) — 新增成功收尾时 per-spec 验证产物 worktree→主树拷回（agent 写在 worktree 真实 `.fenix/` 的产物此前随 worktree 清理丢失，Dashboard 读侧全盲）
