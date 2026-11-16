## Deliverables

```yaml
- path: core/agent_runner/latency.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/self_review.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: tests/test_lane_stall_accounting.py
  kind: new
```

## 1. 停滞总秒供数

- [x] 1.1 core/agent_runner/latency.py：latency_stats 输出补 latency_stall_total_seconds 键（对超 LATENCY_STALL_SECONDS 统计线的样本求和），三常量同值不同义、禁止合并的约束保持并加注释
- [x] 1.2 core/agent_runner/runner.py：_log_run_metrics 的 metric_ctx 组装透传 latency_stall_total_seconds 到 run_metrics 终态行，核对 _metrics_latency 与成功路径两条透传链同覆盖

## 2. 车道级日累计汇总

- [x] 2.1 core/self_review.py：停滞聚合（_collect_api_stall_aggregates / _scan_run_stall_totals）输出按 agent_type 分组的车道级日汇总行（停滞总秒/run 数/最大单次），附阈值标注，同一遍扫描内完成不新增 IO

## 3. 车道日累计阈值告警

- [x] 3.1 core/admin_monitor.py：api-stall 收尾检测循环内增加车道×日累计计数器（读终态 run_metrics 行按 lane+date 求和），超阈值发 info 级 signal 提示 provider 拥塞，去重键=lane+date 每车道每日至多一条；阈值配置化（admin.lane_stall_warn_minutes，缺省各车道统一 30 分钟，0=关闭）；去重经持久键跨重启生效——信号携带稳定 _fp（=lane+date）进 status_hash 指纹位（指纹不含累计秒数），同日复触发经 merge_signal 仅刷 last_seen 不新增记录
- [x] 3.2 core/admin_monitor.py：daemon 重启后当日计数从已落账 run_metrics 行重建；缺新键的存量行按 0 计
- [x] 3.3 core/admin_monitor.py：既有单 run 粒度 api_round_stall_escalated 升级信号行为不变（success 终态豁免语义保留）

## 4. 测试

- [x] 4.1 tests/test_lane_stall_accounting.py：latency_stats 总秒键求和正确（含 0 样本与无停滞 run）、run_metrics 行含新键、两条透传链不漏
- [x] 4.2 tests/test_lane_stall_accounting.py：车道级日汇总分组与阈值标注、lane+date 去重（同日二次触发不再发）、阈值缺省 30 分钟与 0=关闭语义
- [x] 4.3 tests/test_lane_stall_accounting.py：重启重建当日计数、重启后同日重复超阈值不新增第二条 lane+date 记录（持久键去重）、存量行缺新键按 0 计、单 run 升级信号行为不回归