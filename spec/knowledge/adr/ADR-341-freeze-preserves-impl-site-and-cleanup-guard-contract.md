# ADR-341：冻结即保全与清理守护契约（冻结现场两道防线）

date: 2026-11-09
status: accepted

## Context

fast-track 重试耗尽冻结转人工曾不保全实现现场：冻结只写 blocked/frozen/error/告警，实现分支（可携带全部已验证实现提交）与 worktree 随后被自动清理链删除——实证删除者是 legacy 宽限期兜底回收链以无保护 `branch -D` 收尾，孤儿清扫目录侧亦无冻结豁免；分支被删且 STATE `branch` 锚点为空后，unfreeze 续做通道（`_frozen_hold → _resolve_preserved_branch`）不可达，解冻只能从零重派，悬空对象经 `git gc` 回收即整体丢失。

「冻结即保全」已是框架惯例（frozen-terminated、验证管线、repair lane、queue、spec_review 各路径均有 `mark_frozen_hold` 伴调），fast-track 重试耗尽/零变更哨是漏网路径。同时 pre-rmtree 快照只对 dirty worktree 产出（clean 目录无产出），提交已全部完成的分支 ref 是唯一保全载体——保全必须落在冻结时刻，事后补救窗口不存在。

## Decision

确立冻结现场两道防线契约：

1. **冻结即保全不变量**：凡 fast-track 冻结转人工站点（含未来新增站点）在 `freeze_for_human` 之前，对实现分支相对解析基线存在未合并提交的现场 MUST 完成保全——pre-rmtree 快照 + `_frozen_hold: True` + `branch`/`implementer_run` 锚点回写，三键同一原子写窗口不拆分；分支解析与 `_resolve_preserved_branch` 同源三层口径，MUST NOT 另持平行副本；零未合并提交退化为现状行为（不置 hold、不产快照）；保全失败 fail-open（ERROR 审计留痕）不阻断冻结本身。
2. **清理守护正匹配口径**：凡能删 `fenix/<spec>-<ts>` 实现分支或 spec worktree 的自动周期清理入口（含未来新增 sweeper）对 STATE 在册 `frozen=True` 且 `_frozen_hold: True` 的 spec MUST 跳过删除并 WARNING 留痕；守卫只认 STATE 在册条目，STATE 不可解析不触发豁免（不放宽删除行为基线）；守卫只约束自动清理，显式 spec 删除/归档收尾通道（先清 STATE 条目再清现场）MUST NOT 被守卫反向阻断。

## Consequences

- 冻结→解冻→续做全链可达：保全现场经 `unfreeze_spec` 命中 `_resolve_preserved_branch` 续做通道，续做在保全分支上进行而非从零新建；解冻清 `_frozen_hold` 后清理豁免自然解除，滞留的分支/worktree 由下一轮清扫正常回收。
- 既有三键守卫（GC 守卫 (ii)、`_branch_protected_by_state` (c) 款）因防线 1 置位即被激活，无需逐处改写；新增清理入口只须接同一 STATE 正匹配守卫。
- 保全写形态为助手单次锁定写（不复用 `mark_frozen_hold`，其锁内复核要求 `frozen` 已置位、与冻结前保全的时序不相容），其余 `mark_frozen_hold` 调用点行为逐位不变。
- 后续新增冻结转人工站点或清理入口 MUST 按本契约接线；另立保全载体或豁免判据须显式 supersede 本裁定。
