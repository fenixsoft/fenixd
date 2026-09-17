# SUPERSEDED — 已收敛（evo-merge-back-wip-overlap-gate-575976 取代）

本目录与 `evo-merge-back-wip-overlap-gate-575976/` 为**同一需求的两份同源草案**
（本目录 created 2026-09-16，capability `worktree`）。按 `-575976` 的 proposal.md
「同源草案收敛」义务，实现前 MUST 先收敛为一份——以 `-575976` 的**默认策略与
作用域约束为基准**（默认自动收纳、阻塞仅显式配置启用、闸门作用域排除
`spec/changes/**`、阻塞 MUST NOT 计入 merge 熔断记账）。

## 收敛结论

- **生效实现落点**：`spec/changes/evo-merge-back-wip-overlap-gate-575976/`
  （实现分支 `fenix/evo-merge-back-wip-overlap-gate-575976-*`）。
- 本草案的 tasks.md / proposal.md / design.md 不再作为独立实现入口，防止主树
  出现两套语义不同的 merge-back 闸门。
- 两侧草案的默认策略（本目录与 `-575976` 均为「默认自动收纳、block 仅显式配置」）
  与作用域约束（排除 `spec/changes/**`）已核对一致，无语义矛盾残留。
- 历史实现分支 `fenix/evo-merge-back-wip-overlap-gate-1789672392`（f2526a46，
  同功能实现）如后续并入主树，其语义与 `-575976` 实现一致，可安全合并/弃用。
