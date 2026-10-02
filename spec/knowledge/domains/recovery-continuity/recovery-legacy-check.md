<!-- knowledge: capability=recovery-legacy-check rev=1 sources=spec/archive/2026-09-06-add-recovery-legacy-check -->

# 死亡 run 遗产检查与自主收编

实现 run 死亡后的 worktree 与分支注册为遗产并保留观察期，由后继 run 的 agent 自主决定收编或弃用，防止误清仍在消费的产物。

## 现行规则

- 遗产保留：实现 run 死亡（进程消失且未产出成功结果）触发恢复重派时，死亡 run 的 worktree 目录与分支注册为该 spec 的遗产（legacy），保留至「后继 run 成功 merge」或「宽限期超时」二者先到；保留期间孤儿清扫器不回收。宽限期跟随孤儿清扫周期，超时由 sweeper 兜底回收并记审计日志。
- 遗产上下文注入：恢复重派的 implementer 任务书 prompt 注入遗产 worktree 绝对路径、分支名、`git status --short` 快照（脏文件清单，截断至合理长度），并明确指示遗产为只读参考、不得在其中工作；无遗产（首次实现或遗产已被兜底回收）时不注入空遗产段。
- 自主收编决策权：新 run agent 自行 inspect 遗产后选择「收编」——把有价值的半成品移植进自己的 worktree、适配后提交，提交信息注明来源分支（如 salvaged from <分支>），验证链照常验收其产出、不因收编豁免；或选择「弃用」——从干净状态重做，并在任务书响应中声明重做理由。框架不强制其中一种选择，不担保遗产内容正确性。
- 只读边界：遗产期内遗产 worktree 为只读参考——恢复重派不复用遗产 worktree 作为新 run 的工作目录（新建 worktree 的行为不变），锁与派发互斥逻辑不因遗产改变，遗产不出现在任何可派发/可锁定清单中。

## 溯源

- 史前复原 — 迁移期已存在的基线：死亡 run 的遗产（保留分支、worktree）先做遗留检查再决定保留或自主收编，防误清仍在消费的产物
- 2026-09-06 add-recovery-legacy-check（spec/archive/2026-09-06-add-recovery-legacy-check） — 机制化遗产保留与清扫豁免、遗产上下文注入、agent 自主收编决策权与只读边界
