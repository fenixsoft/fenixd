# ADR-349：处置链视图在办富化联查收敛后端聚合端点单点下发

date: 2026-11-11
status: accepted

## Context

处置链页签需要展示超出链状态文件字段面（在办件仅 chain_id/signature/spec/phase/started_at 五字段）的信息：问题描述摘要、Admin/Arbiter 配额进度、run 标识。这些数据分散在 `admin_alerts.json`、arbiter ledger、链状态文件与 escalation 联查中。若由前端逐件自行联查，会形成 N×M 请求数、多处读同一批文件的平行读面，且联查逻辑落入前端后难以为其他消费方复用——与「视图数据单源」纪律直接冲突。

## Decision

在办件富化联查收敛在后端聚合端点 `chain_overview` 单点组装下发：问题描述摘要（同签名最近上升件 description 截断）、Admin/Arbiter 已用计数与上限（escalation/签名配额联查）、run_id（从链上下文尽力提取，不可得置 null）。联查 fail-open（文件缺失/未命中静默降级），数据保持单源不建平行真相源；前端只渲染投影，不做自行联查。后续给处置链视图新增展示字段一律走后端下发通道，前端自联查须显式新裁定。

## Consequences

- `chain_overview` 计算量增加（联查同签名 escalation），数据量级为个位数在办×数十签名，30s 轮询下无压力；联查 fail-open，缺数据降级不阻断视图。
- run_id 系统性不可得（链状态文件字段面所限）时，前端 run 标识显示「—」，进度条以 escalation 联查计数兜底，不伪 0。
- 新增展示字段需前后端投影两侧同步（`chain_overview` 组装 + `services/dashboard.ts` 类型投影），字段契约以聚合端点为单源。
