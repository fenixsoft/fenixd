# 成本与可观测
> 最后更新：2026-10-07 14:39 UTC+8

成本与可观测。覆盖 run 成本采集与本地计价、预算与费控治理、延迟/进度/耗时观测、run 记录流呈现可读性与产物保留策略。

## 能力页

| 能力页 | 简介 | 更新时间 |
| --- | --- | --- |
| [cost-observability](cost-observability.md) | per-spec token 用量累计、金额本地计价展示与预算阈值告警 | 2026-10-03 04:59 |
| [cost-governance](cost-governance.md) | 基础设施失败费控豁免（不耗预算、不进冻结闸门、历史轮次回拨） | 2026-10-03 04:59 |
| [agent-cost-control](agent-cost-control.md) | 单 run 轮次上限与 thinking_tokens 遥测过滤 | 2026-10-03 04:59 |
| [agent-run-token-economy](agent-run-token-economy.md) | run 级上下文经济性指标与网关前缀缓存探针 | 2026-10-03 04:59 |
| [run-latency-observability](run-latency-observability.md) | run 级 API 延迟直方图（摘要日志/失败证据/事后脚本/失明自检） | 2026-10-03 04:59 |
| [api-stall-observability](api-stall-observability.md) | run 期单次 API 往返停滞的时点 WARNING 现场与三字段随 run_metrics 入账（纯读侧不干预） | 2026-10-07 14:39 |
| [run-progress-observability](run-progress-observability.md) | run 层实时任务进度与 tasks.md 快照并行展示 | 2026-10-03 04:59 |
| [run-duration-parsing](run-duration-parsing.md) | run 耗时解析口径（run_id 时间戳 + mtime，attempt 后缀适配） | 2026-10-03 04:59 |
| [spec-duration-persistence](spec-duration-persistence.md) | SPEC 完成时固化总耗时到 STATE.md | 2026-10-03 04:59 |
| [run-stream-noise-reduction](run-stream-noise-reduction.md) | run 流事件分类渲染（心跳静默/信息类语义化/任务回填） | 2026-10-03 04:59 |
| [run-stream-thinking-and-scope](run-stream-thinking-and-scope.md) | thinking 折叠头/思考开关/向前分页与总量计数 | 2026-10-03 04:59 |
| [run-stream-tool-grouping](run-stream-tool-grouping.md) | 工具调用同类连续聚合、语义摘要与耗时标注 | 2026-10-03 04:59 |
| [run-artifact-retention](run-artifact-retention.md) | run 产物生命周期绑定 SPEC 归档（归档即清理），无主车道产物按天龄兜底 | 2026-10-06 07:44 |
| [observability-gaps](observability-gaps.md) | run 终止结构化指标/状态转换 context/审计窗口/日志双写 | 2026-10-03 04:59 |
