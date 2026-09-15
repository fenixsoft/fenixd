# Design: fix-observability-gaps

## Context

三处可观测性失真：run 耗时/成本算了不落盘；状态转换日志无结构化 context，时间轴靠正则考古；审计窗口与 supervisor 双写不合理。详见 proposal。

## Goals / Non-Goals

**Goals**：让耗时/成本可事后直接读取；让时间轴优先消费结构化字段；修正审计窗口与双写。

**Non-Goals**：不重建日志体系；不改告警等级策略；不做指标可视化前端。

## Decisions

### D1：单一结构化指标记录，取代三车道分治
run 收尾（成功/失败两分支）各写一条含 `duration_seconds / usage / cost_usd / terminal / provider` 的记录，复用既有日志落盘设施（不新建 metrics 目录与消费者）；dashboard 时间轴/成本页按需读取。
**替代**：新建 `.fenix/metrics/*.jsonl` 独立文件——本变更先复用日志，若后续确需独立文件另立 spec。

### D2：Transition 带 context，读侧双轨
写侧补 `trigger_run_id / agent_type / channel`；读侧时间轴**优先**读结构化 context，正则降为历史兜底（保证旧日志不丢事件）。这是「写侧加字段不改格式 + 读侧双轨」的低风险路径。
**替代**：改用独立事件文件——否决，与「文件即状态、日志可读」的既有设计冲突。

### D3：审计窗口与双写
`admin_state_history` 保留窗 1h → ≥24h（flapping 检测仍按窗算，不受影响）；supervisor 日志去掉 print 或改 stderr 单向（避免与 stdout 重定向到同一文件造成的每行双写）。

## Risks / Trade-offs

- [新字段增加日志体积] → 仅终态与转换点记录，量级可控。
- [时间轴双轨逻辑复杂] → 以「结构化优先、正则兜底」的顺序收敛为单一函数，配两路用例。
- [保留窗提升致文件增大] → 24h 内状态变化量小；**注意 `changes` 只按时间裁剪、无条数上限**（`core/admin_monitor.py:1970`），故须在实现时实测条目量级，必要时补条数上限（`:1956-1982`）。

## Migration Plan

四阶段独立 commit：①指标落盘 ②Transition context ③时间轴消费 ④窗口+双写。每阶段全量 pytest，收尾在真实 daemon 日志中实证新字段。**回滚**：逐阶段回退。
