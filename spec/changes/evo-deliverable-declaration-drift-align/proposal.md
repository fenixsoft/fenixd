# Proposal: deliverable-declaration-drift-align

## 问题

重构（拆包/拆文件）落地后，同批 spec 的 Deliverables 声明段仍登记旧单文件路径（如 core/worktree_manager.py、core/pm_engine/dispatch.py），交付物守卫对账缺件触发 deliverable-dispute 异议，全部为可机器判定的「陈旧路径笔误」却各自走满人工裁决通道：2026-09-17T19:55Z/20:39Z/21:24Z 三连 blocked，admin 两次机械裁决 verdict=typo 收场（dispute_audits.jsonl 两条 + 4118afc9）。同批同源两份草案（evo-merge-back-wip-overlap-gate 与 -575976）被先后各派发实现 run（SUPERSEDED.md 记载「实现前 MUST 先收敛」但派发未强制）。

## 证据

- fenixd.log:30920/31742/32225：三条交付物守卫缺件异议 ERROR（路径均为拆包前单文件）
- .fenix/dispute_audits.jsonl：两条裁决 verdict=typo、actual_path=core/worktree_manager/mergeback.py / core/pm_engine/dispatch/queue.py（reasoning：6491c960 拆包后文件不存在）
- core/deliverables.py:1457-1460：孤儿判定边界「历史命中=曾存在 → 走人工，不判孤儿」——漂移形态无自动通道
- spec/changes/evo-merge-back-wip-overlap-gate/SUPERSEDED.md：同源草案收敛义务「实现前 MUST 先收敛」但未在派发前强制

## 设计思路

1. **漂移笔误机械对齐**（孤儿预分类旁扩一类，仅异议分支可达）：交付物守卫缺件异议时，若声明路径在主树与实现分支 HEAD 均缺、且 git 历史命中（曾作为文件存在，即拆包/改名漂移），则定位候选新落点——旧路径 basename 对应包目录内、且落在本次实现分支改动集合（`git diff --name-only <merge-base>..<branch>`）里的 `.py` 文件（复用 `add-declaration-relocation-protocol` 已落地的陈日信号/生效声明解析/改写/凭据原语）：
   - 候选唯一且在分支 HEAD 真实存在 → 机械改写**生效声明所在位置**（非主树直写）并立即提交，留审计（verdict=drift-aligned + type=relocation + actual_path），解除 blocked 自动重入实现
   - 候选零/多、生效声明无落盘位置（分支来源）、或候选不在分支 HEAD → fail-open 维持现状走人工通道
2. **派发前同源草案收敛检查**：`_on_spec_ready`（并以同口径覆盖队列候选筛选入口）派发 implementer/fast-track 前，检查本 spec 目录自身是否含 SUPERSEDED.md（已被取代标记）→ 命中则置 blocked（error=同源草案收敛义务未满足，指向 SUPERSEDED.md 路径），禁止双 run 派发；被该页点名的生效落点一侧 MUST NOT 被拦截。

> 本 SPEC 与 `add-declaration-relocation-protocol`（2026-09-18 已 push 入库）的分工：后者覆盖实现 run **未提异议**时 `_adjudicate_deliverable_missing` 链上的陈日重定位（`_preclassify_stale`）；本 SPEC 覆盖实现 run **已提 deliverable-dispute 异议**时 `queue.py` 争议分支内的同族机械对齐——该分支不进入 `_adjudicate_deliverable_missing`，故 `_preclassify_stale` 不可达，本轮三次 blocked 事故正落在这一段。

## 范围

- 覆盖交付物守卫缺件异议的机械预分类（与 deliverable-dispute-orphan-preclassify 并列、互斥：孤儿=零历史命中；漂移=历史命中+目标候选存在）
- 覆盖 implementer 派发前的同源草案收敛检查（engine.py _on_spec_ready 路径）
- 不改变人工裁决兜底（机械对齐不唯一时 fail-open）