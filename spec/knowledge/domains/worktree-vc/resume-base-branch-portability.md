# 恢复续做基线分支可移植解析

<!-- knowledge: capability=resume-base-branch-portability rev=1
     sources=spec/archive/2026-10-08-evo-fix-resume-base-branch-portability -->

框架所有「分支相对基线的未合并提交数」类判定经共享解析器单源取基线分支，使恢复保留续做、分支枚举、零提交门与零变更哨在任意主干命名的仓库（main / master / origin/HEAD 指针）语义一致。

## 规则

- 单源解析器：`core/git_base_branch.py::resolve_base_branch(project_root, timeout=15.0) -> str`，解析顺序 `git symbolic-ref --short refs/remotes/origin/HEAD`（去 `origin/` 前缀）→ 本地存在 `main` → 本地存在 `master` → 回退常量 `"main"`；本地分支探测用 `git rev-parse --verify --quiet <ref>`（一次子进程、退出码判定）。模块不导入 fenixd.py（core 模块导入 fenixd 会成环），也不放进 worktree_manager mixin（state_machine 的闸门在 worktree_manager 为 None 时早退前也要用基线）。
- 超时与缓存：每次 git 子进程调用带超时（缺省 15s，与 PRESERVE_AHEAD_COUNT_TIMEOUT_SECONDS 口径一致）；结果按 project_root 进程内缓存（附显式 `reset_cache()` 供测试重探）；恢复路径为启动一次性调用，无热路径压力。
- 失败语义分层：解析器自身吞 TimeoutExpired/OSError 回退常量、不向调用方抛异常、无 None 返回语义；各调用点的失败方向由替换后的 git 查询自身维持，不因换基线重写——恢复续做闸门 rev-list 非零退出/超时/计数 ≤0 维持 `(None, None)` 早退清空重建；worktree 查询（find_branches_by_spec / has_pending_merge / pending_merge_since）失败维持 fail-closed 返回空/None；终态零提交门维持 fail-open（门自身故障不打断正常收口）；branch_guard `_branch_commit_count` rev-list 失败维持返回 None、调用方 fail-open。
- 消费点全量收敛，禁止新增调用点各自硬编码主干名或另建基线来源：恢复续做判定 `_resolve_preserved_branch`（取消保持恢复、解冻保留续做等共享同一判定）；worktree_manager/queries 的候选剔除/排序（含「已含基线」分组键 `merge-base --is-ancestor`）、has_pending_merge、pending_merge_since；agent_runner/runner 终态零提交门；agent_runner/prompt_builder legacy 提交快照（`git log --oneline <基线>..branch`）；fenixd `_preserve_base_branch`/`_ahead_commit_count`（保全条目 ahead_commits 字段来源，保留函数签名与调用点、委托共享解析器）；pm_engine/verification/branch_guard `_branch_commit_count`（零变更哨与验证分支守卫的共用单一来源，基线候选循环与 origin/HEAD 二连击探测收敛为先解析后 rev-list 一次）。
- 非 main 主干仓库的行为面：master 主干无 remote 仓库解析为 master——被排水中断的 WIP 分支走保留续做而非「三处锚点均不可得」清空重建；分支命名空间枚举可命中候选；终态零提交门按门规则真实拦截零提交且 dirty 的收口；legacy 快照返回提交清单；零变更哨对含提交分支返回非 None 计数、可正常判零变更空转；保全条目 ahead_commits 为真实计数。
- main 主干仓库零漂移：解析结果同为 main，rev-list 同参，枚举、排序、闸门、哨行为逐项不变。
- 闸门以实数为判：基线单源化不得引入误保留或误杀——保留判定仍要求 rev-list 计数 >0，真零提交分支仍走清空重建并留 WARNING；零提交门仍要求「零新提交且 dirty 取证非空」才拦，零提交且工作区干净的真空转归零变更哨管辖。

## 溯源

- 2026-10-08 evo-fix-resume-base-branch-portability（spec/archive/2026-10-08-evo-fix-resume-base-branch-portability） — 新增共享基线解析器（origin/HEAD → 本地 main → 本地 master → 回退 main，带超时与按 project_root 缓存），把 6 处硬编码 `main..<branch>`、branch_guard 基线候选循环与 fenixd 保全统计收敛到单源
