<!-- knowledge: capability=worktree-result-readback rev=1 sources=spec/archive/2026-09-02-fix-worktree-spec-seeding -->

# worktree 结果回读

实现结果从活跃 implementer worktree 读回主树侧消费：结果文件与任务勾选的读取路径按生命周期与 worktree 归属绑定，避免读空。

## 现行规则

- 实现结果 worktree 优先读取：`core/pm_engine.py` 读取实现 Agent 的结果（`.fenix-run-result.json`）时，优先从该 SPEC 的活跃 implementer worktree 读取——按 `impl-<spec>-*` 匹配 worktree（存在多个取最新），该 worktree 内存在结果文件则读取之；否则回退项目根的 `.fenix-run-result.json`。本规则仅针对 implementer 结果读取；verifier / planner 的结果读取位置维持项目根。
- 任务进度展示 worktree 优先（implementing 阶段）：`bin/statusline.py`、`core/dashboard/data.py` 与 `/fenix-status` skill 的任务进度解析，对状态为 `implementing` 的 SPEC 优先从该 SPEC 活跃 implementer worktree 的 `spec/changes/<spec>/tasks.md` 读取勾选进度；worktree 不存在或文件缺失时回退主仓库。非 implementing 状态（testing / verified / done / bug-found 等）一律从主仓库读取。

## 溯源

- 史前复原（存量基线） — 实现结果（勾选、结果文件、交付物）从 worktree 读回主树侧消费，读回路径与 worktree 归属绑定
- [2026-09-02 fix-worktree-spec-seeding](spec/archive/2026-09-02-fix-worktree-spec-seeding/) — 固化 implementer 结果文件 worktree 优先（impl-<spec>-* 最新匹配）回退项目根、verifier/planner 读取位置不变、任务进度展示按 implementing 状态分流读取
