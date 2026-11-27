# add-lane-stall-daily-budget-accounting 设计

## 现状锚点

- core/agent_runner/latency.py:192 latency_stats 输出 rounds/median/p90/max/stalls/stall_ratio——无总秒键；:46 classify_round_stall 与三常量（60 统计线/120 期内告警/300 分级线）语义不合并约束。
- core/agent_runner/runner.py:10506 _log_run_metrics（metric_ctx 组装 :10570-10595；透传链 _metrics_latency :572 与成功路径 :5980）。
- core/self_review.py:1804 _collect_api_stall_aggregates / :1751 _scan_run_stall_totals（有界流式扫描）、发射点 :2518-2530——数据摘要第 6 节来源，逐 run 行无分组。
- core/admin_monitor.py api-stall 收尾检测循环（信号创建约 :3480-3530，单 run 去重、success 豁免）；信号入库入口 core/admin_store.py:1009 merge_signal。
- core/agent_runner/liveness.py:1723 _supervision_deadline_action / :990 _liveness_snapshot——无 stall 维度（预算单列列非目标）。

## 设计决策

1. 总秒键在 latency_stats 一处求和（对超统计线样本求 sum），下游（run_metrics / self_review / admin_monitor）全部复用该键——避免三处各自重算导致口径漂移。
2. 车道日汇总挂在既有 self_review 扫描内（同一遍、零额外 IO）：聚合输出加 agent_type 分组维度，不新建扫描器。
3. admin_monitor 计数器按（lane, date）在内存聚合终态 run_metrics 行；daemon 重启后当日计数从已落账 run_metrics 行重建（扫描当日终态行求和），避免重启丢计数漏发；info 级不进人工队列（HUMAN_SEVERITIES 只收 critical/major），噪声面可控。
4. 去重键=lane+date：provider 拥塞按 30 分钟阈值 3/3 活跃窗都会触发，按车道×日去重把告警频率压到每车道每日至多一条。去重状态不依赖内存：信号携带稳定 `_fp`（=lane+date）走 `_signal_status_hash` 的 daemon 级指纹位（admin_monitor.py:5724，spec=null 路径 sha1("daemon:"+signal_type+fp)），经 merge_signal 持久键合并（admin_store.py:1030）——同日复触发仅刷 last_seen 不新增记录；指纹不含累计秒数（避免文案数值变化被判「状态变化」拆出第二条记录），跨日 date 变化指纹自然过期；daemon 重启后无需重建去重状态（决策 3 的重启重建只补计数，不补去重）。
5. 不动 liveness 判定链与 dashboard：预算停滞单列与健康面曲线各拆独立立项（成本收益不同档，本 spec 聚焦轻量记账）。

## 风险

- 存量 run_metrics 行无新键：计数按 0 计（向后兼容，不回填历史）。
- info 信号噪声：lane+date 去重 + 阈值缺省 30 分钟 + info 级不进人工队列三重收敛。
- 口径漂移：三常量语义不合并的既有约束在求和逻辑处显式注释，测试固化。