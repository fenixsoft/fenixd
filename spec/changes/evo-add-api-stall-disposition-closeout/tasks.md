## Deliverables

```yaml
- path: core/agent_runner/runner.py
  kind: modify
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: tests/test_api_stall_disposition.py
  kind: new
```

## 1. 终态 latency 透传

- [ ] 1.1 core/agent_runner/maintenance_runs.py：_log_lane_run_metrics（现 :1195-1247）签名增加 latency 参数，五个车道收尾调用点（现 :474/:812/:1544/:2304/:3188）传入 _run_agent 返回的 stall stats（现 :1952 解包后弃用的 _stall_latency）。
- [ ] 1.2 core/agent_runner/runner.py：非成功终态的 _log_run_metrics 调用点经公共 helper 透传 latency（现 16 处仅成功路径 :5255 透传；:9063-9065 零样本回退保持不变）。

## 2. 升级信号与受控重试

- [ ] 2.1 core/admin_monitor.py：AdminMonitor 检测面新增 api_round_stall_escalated 信号（merge_signal，dedup 键对 spec=null 周期 run 以 run_id 进 hash 位，单 run 至多一条）。
- [ ] 2.2 core/agent_runner/maintenance_runs.py：车道收尾检测「warning-escalated 且 run 收尾 error」时登记 stall_redispatch 意图（复用现 :2280-2298 附近 ratelimit 意图落盘形态，与 ratelimit/zero_row 意图互斥，上限 1 次/monitor 生命周期）。
- [ ] 2.3 core/admin_monitor.py：消费 stall 意图（复用冷却+单飞骨架，:2092/:2160/:2257-2267 按意图类型分发），以 redispatch_of 链重派一次；runner.py:6404-6406 与 :6963-6969 注释按新行为更新。

## 3. 留痕

- [ ] 3.1 core/agent_runner/runner.py：api_round_stall 日志 context 补当轮上下文规模（input tokens）与 provider 字段。

## 4. 测试

- [ ] 4.1 tests/test_api_stall_disposition.py：error 终态 run_metrics 的 latency_* 与过程指标一致；成功终态透传不回归；无停滞 run 行为零变化。
- [ ] 4.2 tests/test_api_stall_disposition.py：warning-escalated→信号 1 条且同 run 去重；「warning-escalated 且收尾 error」→stall 意图登记/上限 1 次/与 ratelimit、zero_row 互斥/redispatch_of 指向原 run；「曾停滞但正常完成」→无信号无意图。