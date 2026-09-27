# ADR-011：自动审批由 daemon 驱动

date: 2026-09-02
status: accepted

## Context

push 审批（`/fenix-approve`）运行在 Claude 会话层，本质是人工动作。无人值守场景（auto 模式：SPEC 到达 done 后自动 push 并标记 pushed）不能依赖会话层触发——会话不常驻，自动化必须由常驻组件执行。自动 `git push` 是显著外向行为，默认态与失败路径须一并裁定。

## Decision

- 审批模式 `gates.approve_mode` 取 `manual`（默认）或 `auto`；auto 模式下由 daemon（pm_engine）在 SPEC 到达 done 后执行推送：解析分支名（优先 STATE.md 的 `branch` 字段，否则 `fenix/<spec>`）→ `git push origin <branch>`（带超时保护）→ 成功则转换 `pushed`。
- manual 是恒定默认值：auto 仅在用户显式配置时启用。
- 推送失败不静默：保留 done 状态并记录 error，人工 `/fenix-approve` 兜底；不重试轰炸。
- 自动审批与人工审批复用同一状态转换入口，语义一致。

## Consequences

- 无人值守链路（done → pushed）闭环，审批链路的自动化职责归属 daemon 而非任何会话层 skill。
- 外向推送由显式配置门控，误推风险被默认 manual 抑制；失败路径保证 SPEC 停留在可人工介入的状态，不会因推送故障丢失完成态。
