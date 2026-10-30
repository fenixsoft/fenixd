# 提案：API 停滞处置闭环（升级接信号面 + 受控重试 + 终态 latency 透传）

## 背景

评审车道 API 往返停滞已连续 7 窗记录（逐窗白等 6.4~14.2 分钟，2026-10-23 窗单轮 726.3 秒创日志新高、占墙钟 89.3%），但分级事件（api_round_stall，grade=warning-escalated）发出后没有任何处置入口：仅 logger 落日志（core/agent_runner/runner.py:6440-6519，注释明写「不 kill、不重派、不触发人工告警」:6471），admin 信号面零接入（写入函数唯一 core/admin_store.py:662 merge_signal，调用方仅 admin_monitor.py:4629/:4684/:4689），数据摘要 admin 面按 kind=signal 计数恒 0。warning-escalated 全日志 8 次（10-15 至 10-23）无一处置，缺口点名自 10-17 起 6 窗延续。

叠加终态清零：终态 run_metrics 的 latency_rounds/latency_stalls/latency_max 恒 0/0/null（fenixd.log:6895），与过程指标（:6893，10 轮/2 停滞/max 726.284）同 run 自相矛盾——只读终态行的下游（预算统计、重派判定、离群初筛）完全看不到停滞。

根因（evo-1792779466 复核定位）：①终态行由 core/agent_runner/maintenance_runs.py:1306-1348 _log_lane_run_metrics 调 _log_run_metrics 时不传 latency（runner.py:9111/:9145-9147 零样本回退 0/0/None），而数据经 _run_agent 返回 tuple 第 5 元素已在收尾作用域（maintenance_runs.py:387/:854/:1462/:2083/:3248 五处解包 _stall_latency 后弃用）；runner.py 内 16 个调用点也仅成功路径（:5301-5306）透传。②停滞事件路径无任何 admin_store 调用。

## 目标

1. 终态 run_metrics 如实透传 latency_rounds/latency_stalls/latency_max（车道链路 5 个收尾点必须，runner 内非成功终态点经公共 helper 覆盖）。
2. warning-escalated 写入 admin 信号面（signal_type=api_round_stall_escalated），同 run 去重。
3. warning-escalated 且 run 收尾失败/零进度时触发一次受控重试：车道层登记重派意图（复用 ratelimit_redispatch 骨架），上限 1 次、冷却+单飞，与其他意图互斥。
4. api_round_stall 事件 context 补记当轮上下文规模（input tokens）与 provider，积累归因证据。

## 非目标

- 不做停滞根因裁决（网关排队/长上下文/本地网络三假说留待留痕积累）。
- 不改停滞分级阈值与分级纯函数（core/agent_runner/latency.py）。
- 不做多次重派与自动换供应商。