<!-- knowledge: capability=worktree-isolation rev=3 sources=spec/archive/2026-09-02-fix-worktree-agent-cwd,spec/knowledge/_inbox/done/memory-distill-agent-prompt-rules.md,spec/knowledge/_inbox/done/memory-distill-ops-runbook.md -->

# worktree 隔离与路径锚定

实现工作在独立 git worktree 内进行：implementer 子进程的 cwd 指向 worktree，主树不被实现期改动污染，完成后经 merge-back 合入主树。本页同时覆盖隔离失效的主形态与对策——注入上下文路径锚定导致写错位置、跨树操作的验证错位、主树并行改动的判别纪律。

## 现行规则

- cwd 隔离：implementer 的 claude 子进程以 worktree 目录作为工作目录（cwd）运行——`agent_runner._run_claude` 的 `subprocess.Popen` 传入 `cwd=<worktree 路径>`；实现者的所有相对路径文件编辑（Read/Edit/Write）与 git commit 全部落在该 worktree（如 `.claude/worktrees/impl-<spec>-<ts>`），运行记录 init 事件的 `cwd` 等于 worktree 路径。运行期间主树保持干净（无该 SPEC 相关的未提交改动）。
- 成功后合并回主树：implementer 成功运行后将 worktree 分支（`fenix/<spec>-<ts>`）合并回主树，使用保留历史的 `git merge --no-ff`（或等价机制），具备幂等性（分支已为主树 HEAD 祖先时再次触发合并幂等跳过，不产生新 merge commit 或报错）。合并失败（如冲突）将 SPEC 标记为 error、不推进 `implemented`，STATE.md error 记录冲突详情，由既有重试机制重建 worktree 重做。
- tasks.md 读取路径与实际工作目录一致：`data.parse_tasks` 在 `implementing` 状态读取 worktree 的 tasks.md（实现者实时勾选处），merge-back 完成后的状态（implemented/testing/done）读取主树的 tasks.md（合并带回的勾选状态）。Dashboard 任务进度在任意生命周期状态反映实现者标记的完成状态（run 记录实时叠加与 tasks.md 勾选的并集）。
- 验证管线衔接：verifier 在主树运行并验证 merge 后的实现；implement → merge → verify 周期正常闭合（实现成功 → 合并回主树 → 主树验证 → 推进 verified/done）。
- 路径锚定防线：注入上下文里的任何绝对路径都可能成为模型的落盘锚点——skill 注入文本首行的主树绝对路径即可让 implementer 全程写主树（39 次写盘 0 次 worktree 的隔离失效实证）。现行防线三件套：`.fenix/hooks/block-main-tree-write.py` PreToolUse 拦截（主树写入 deny + 纠偏提示，白名单仅 `.fenix/verify-progress/` 进度目录）、runner 注入 `FENIX_RUN_PROJECT_ROOT` / `FENIX_RUN_WORKTREE` 环境变量、implementer 提示词工作目录段显式声明。
- 「agent 写错位置」排查顺序：/proc cwd（先排除 spawn 侧问题）→ 转录 tool_use file_path 分布 → 其调用的 skill 注入文本。
- 跨树操作纪律：会话 cwd 已切进 worktree 后改主树文件、再在 worktree 跑验证，验证的永远是旧代码（制造「修复无效」假象）——跨树操作显式 cd，或双树各验。
- 主树手工改动遇磁盘异动的判别：函数/导入被删时先判别误伤 vs 并行 worker 重构——调用点清零 + 测试配套删 + 编译自洽＝重构让路（勿回滚）；不满足则按误伤恢复。
- worktree 内脚本定位项目根不可按 `__file__` 目录层级推断（worktree 无 gitignored 的 `.fenix` 层级、路径深度与主树不一致）：需要 `.fenix` 布局时以自引用软链补齐（`ln -s <worktree> <worktree>/.fenix`），或显式传项目根（`--project` / `FENIX_PROJECT_ROOT`）。
- dist 回退假象判别（「代码被冲掉」先查这个）：先 `git diff HEAD -- <file>` 核对工作树源码是否真丢；源码在而页面行为旧 → grep dist 产物定新旧定性——构建期源码被 stash 走时产物 hash 可能不变但内容旧，`npm run build` 重建后 hash 必变才算带上新码；dist 回退只需重建，不是代码丢失。bundle 特征 grep 用 ASCII 功能特征（中文被 minifier 转 `\uXXXX` escape，恒空命中），页面组件在 async chunk 不在主包。

## 溯源

- 史前复原（存量基线） — 实现工作在独立 git worktree 内进行，主树不被实现期改动污染；完成后经 merge-back 合入主树
- 2026-09-02 fix-worktree-agent-cwd（spec/archive/2026-09-02-fix-worktree-agent-cwd） — 固化 Popen cwd 指向 worktree、merge-back `--no-ff` 幂等合回、tasks.md 读取路径按生命周期分流与 implement→verify 周期不回归
- 2026-11-04 memory-distill-agent-prompt-rules（spec/knowledge/_inbox/done/memory-distill-agent-prompt-rules.md） — 折叠路径锚定防线（PreToolUse 拦截 + FENIX_RUN_* env 注入 + 提示词工作目录段）、写错位置排查顺序、跨树操作验证错位纪律、主树磁盘异动误伤 vs 并行重构判别
- 2026-11-04 memory-distill-ops-runbook（spec/knowledge/_inbox/done/memory-distill-ops-runbook.md） — 折叠 worktree 内脚本项目根定位纪律（__file__ 推根不可靠、自引用软链或显式传根）与 dist 回退假象判别配方（git diff 核对、产物 hash 新旧定性、ASCII 特征 grep）
