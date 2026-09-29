<!-- knowledge: capability=mergeback-inplace-repair rev=2 sources=spec/archive/2026-09-09-add-merge-back-repair-lane,spec/archive/2026-09-19-fix-recovery-branch-anchor-without-worktree -->

# merge-back 原位修复（repair 车道）

语义冲突导致 merge-back 失败时的原位修复通道：保留实现分支与工作现场，派 repair agent 在分支一侧把 main 合入解决冲突，而非 abort 后全新重派。

## 现行规则

- 通道入口：merge-back 失败且产物自愈与 ignored-DU 自愈均不适用（冲突含语义文件）时进入 repair：保留实现分支及其工作现场派 repair agent 原地修复。全部冲突路径均为构建产物且自愈成功时不派发 repair agent（自愈即收口）。
- 修复方向与主树干净态：repair agent 在实现分支一侧修复——把 main merge 进分支、解决冲突后 commit。派发 repair 前框架保证主树处于 merge abort 后干净态（无未合并条目、MERGE_HEAD 等残留）。repair 期间主树无需冻结：其他 spec 的 merge-back 照常推进主树；re-merge-back 因主树再度前进产生新冲突时按既有冲突处理路径与熔断计数处理。
- 修复期状态表达：repair run 运行期 spec 的 `status` 保持 `implementing`（repair 是 implementing 内部的一条车道，不引入新状态）。run 到达终态成功时、re-merge-back 执行之前，写入持久「待 re-merge-back」标记（实现分支已含 main 的合并且冲突已解决，仅剩重新合并进主树；记录分支与 run_id）。标记在 re-merge-back 成功（转入 `implemented`）、同一失败链进入下一轮 repair、或放弃回退 fallback 重派时清除；repair run 运行期间 MUST NOT 写标记。该标记是重启后区分「在飞实现」与「已修复待合并」的唯一持久化表达，恢复链据此走 re-merge-back 路径。
- 载体三态：repair 以实现分支为载体，按现场存活状态处理——(a) 原 worktree 存在 → 原地进入该 worktree，未跟踪构建资产（node_modules、构建缓存）保留；(b) worktree 已清理但分支存在 → 在该分支上创建新 worktree 进入；(c) 分支不存在（已并入主树或已清扫）→ 回退 fallback：从 main 新建 worktree 全新重派，prompt 注入 merge 失败上下文。
- 遗产认领竞态防护：repair 认领登记在 `_legacy` 的 worktree/分支时走与 fast-track 复用一致的 take 动作（认领时从 `_legacy` 摘出），保证孤儿清扫 sweeper 不在 repair 进行中按宽限期回收现场。
- prompt 形态：必含 spec 身份与实现目标简述、冲突文件清单摘要（来自 merge 输出与 git status）、修复方向说明（把 main 合入分支、解决冲突、运行测试、commit）；不注入原 worktree 地址等间接情报（agent 即在现场，冲突状态可自查）。repair agent 无法解决冲突时显式输出失败结论，框架据此回退。
- 预算与轮次：repair 轮计入该 spec 的实现预算（token 记在该 spec 名下，不记为独立消耗）；同一 merge 失败事件链内 repair 最多 2 轮，超限回退 fallback 全新重派，本轮失败链内不再派 repair。
- 锚点先于载体清理：re-merge-back 成功路径中，实现分支与 `implementer_run` 写入 STATE 的动作发生在清理 repair worktree 之前——不允许出现「worktree 已删而 branch 仍为 null」的中间态。

## 溯源

- [2026-09-09 add-merge-back-repair-lane](spec/archive/2026-09-09-add-merge-back-repair-lane/) — 新增语义冲突 repair 通道：分支载体三态、修复方向反转与主树干净态、遗产认领竞态防护、prompt 形态约束与 2 轮预算约束
- [2026-09-19 fix-recovery-branch-anchor-without-worktree](spec/archive/2026-09-19-fix-recovery-branch-anchor-without-worktree/) — 新增「待 re-merge-back」持久标记与修复期状态可区分性（运行期不写标记、三时机清除）、re-merge 成功路径先落锚点再清载体的顺序不变式
