# Proposal: deliverable-declaration-drift-align

## 问题

重构（拆包/拆文件）落地后，同批 spec 的 Deliverables 声明段仍登记旧单文件路径（如 core/worktree_manager.py、core/pm_engine/dispatch.py），交付物守卫对账缺件触发 deliverable-dispute 异议，全部为可机器判定的「陈旧路径笔误」却各自走满人工裁决通道：2026-09-17T19:55Z/20:39Z/21:24Z 三连 blocked，admin 两次机械裁决 verdict=typo 收场（dispute_audits.jsonl 两条 + 4118afc9）。同批同源两份草案（evo-merge-back-wip-overlap-gate 与 -575976）被先后各派发实现 run（SUPERSEDED.md 记载「实现前 MUST 先收敛」但派发未强制）。

## 证据

- fenixd.log:30920/31742/32225：三条交付物守卫缺件异议 ERROR（路径均为拆包前单文件）
- .fenix/dispute_audits.jsonl：两条裁决 verdict=typo、actual_path=core/worktree_manager/mergeback.py / core/pm_engine/dispatch/queue.py（reasoning：6491c960 拆包后文件不存在）
- core/deliverables.py:1457-1460：孤儿判定边界「历史命中=曾存在 → 走人工，不判孤儿」——漂移形态无自动通道
- spec/changes/evo-merge-back-wip-overlap-gate/SUPERSEDED.md：同源草案收敛义务「实现前 MUST 先收敛」但未在派发前强制

## 设计思路

1. **漂移笔误机械对齐**（孤儿预分类旁扩一类）：交付物守卫缺件异议时，若声明路径在主树与实现分支 HEAD 均缺、且 git 历史命中（曾作为文件存在，即拆包/改名漂移），则在全仓（core/ 下递归）扫描候选新落点：
   - 候选唯一 → 机械改写声明（tasks.md Deliverables 段 path 更新）留审计（verdict=drift-aligned + actual_path + 证据链接），解除 blocked 自动重入实现
   - 候选零/多（无法唯一定位）→ fail-open 维持现状走人工通道
2. **派发前同源草案收敛检查**：_on_spec_ready 派发 implementer 前，检查 spec/changes/ 下是否存在同源草案（本 spec 目录被其它 spec 的 SUPERSEDED.md 声明已取代，或本 spec 自身是 SUPERSEDED 页目标之外的同名草案）→ 命中则本 spec 置 blocked（error=同源草案收敛义务未满足，指向 SUPERSEDED.md 路径），禁止双 run 派发。

## 范围

- 覆盖交付物守卫缺件异议的机械预分类（与 deliverable-dispute-orphan-preclassify 并列、互斥：孤儿=零历史命中；漂移=历史命中+目标候选存在）
- 覆盖 implementer 派发前的同源草案收敛检查（engine.py _on_spec_ready 路径）
- 不改变人工裁决兜底（机械对齐不唯一时 fail-open）