# Proposal: fix-observability-gaps

## Why

框架的日志密度与审计文件种类在同类自研系统中属上乘，问题不在「缺日志」，而在**三处结构性失真**，使事故复盘依赖间接证据：

1. **关键指标从不落盘**：run 收尾时 `duration = time.time() - start_time` 已算出却没进日志（实测 `fenixd.log` 中 duration 命中为 0）；主车道的 `cost_usd` 不入任何汇总，dashboard 时间轴靠计价表现算。这解释了「total_duration 从未生效」的现象：耗时/成本事后不可重建，烧钱事故无法量化归因。
2. **状态转换日志零上下文、下游靠正则反解析**：`state_machine` 的 `Transition: <spec> <from> → <to>` 无结构化 context（实测 469/469 条全无），而 dashboard 时间轴完全依赖对该 message 的正则匹配重建——日志格式成了跨模块字符串契约，格式微调即静默断链。
3. **审计与告警存在静默丢失路径**：`admin_alerts.json` 读损坏静默清库（另见 `fix-robustness-edge-cases`）；审计保留窗口互相矛盾（`admin_state_history` 仅 1 小时、`admin_alerts` 上限 150 条）；supervisor 日志每行双写。

## What Changes

- **run 收尾结构化指标落盘**：run 终止时写入单一日志/指标记录，含 `run_id / spec / agent_type / duration_seconds / turns / usage 四分项 / cost_usd / terminal / provider`。
- **状态转换带结构化 context**：`Transition` 日志携带 `trigger_run_id / agent_type / channel`；dashboard 时间轴改为消费结构化 context，正则匹配降为兜底。
- **审计窗口与双写修正**：`admin_state_history` 保留窗由 1 小时提升到 ≥24 小时；修正 supervisor 日志双写。
- （与 `fix-robustness-edge-cases` 的分工：告警存储抗损坏与 logger 旁路收敛那边处理；本 spec 只做指标落盘、转换 context、审计窗口。）

## Capabilities

### New Capabilities

- `run-metrics-persistence`: run 终止指标（耗时/用量/成本）的落盘契约与消费方式。

### Modified Capabilities

- `run-latency-observability` / `cost-observability`: 指标由「日志行/现算」升为「结构化落盘 + 可消费」。
- `spec-timeline-accuracy`: 时间轴由「正则考古」改为「优先消费结构化转换事件」。
- （可能的既有能力）`admin-health-monitor`: 状态历史保留窗口调整。

## Impact

- **代码**：`core/agent_runner/runner.py`（收尾日志，实测存在，收尾分支 `:3183-3201` / `:3271-3304`）、`core/state_machine.py`（`transition` 与 `transition_gate` 两条写路径的 context）、`core/dashboard/data.py`（消费结构化 context；`core/dashboard/data/timeline.py` 系前序未实现 SPEC 的规划路径，当前不存在）、`core/admin_monitor.py`（保留窗）、`bin/fenixd_supervisor.py`（双写）。
- **API**：日志/指标格式为新增字段（向后兼容）；时间轴读侧优先新字段、旧日志走正则兜底。
- **测试**：新增指标落盘、转换 context、时间轴消费用例；既有 `test_dashboard_timeline*`、`test_cost_observability`、`test_admin_health_monitor` 为护栏。
- **注意**：与可读性/健壮性重构有文件重叠，依赖链排在其后。
