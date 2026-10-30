## Deliverables

```yaml
- path: core/agent_runner/runner.py
  kind: modify
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: core/agent_runner/result_gate.py
  kind: modify
- path: tests/test_api_stall_disposition.py
  kind: new
```

## 1. 终态 latency 透传

- [x] 1.1 core/agent_runner/maintenance_runs.py：_log_lane_run_metrics（现 :1306-1348）签名增加 latency 参数（缺省 None，向后兼容既有调用与车道单测打桩），五个车道收尾调用点（现 :564/:927/:1671/:2440/:3339）传入 _run_agent 返回的 stall stats（:387/:854/:1462/:2083/:3248 五处解包的 _stall_latency）；各车道在 try 前预初始化 `_stall_latency = None`（_run_agent 抛出路径无 stall stats，按零样本语义传 None，与同段 turns=0/usage_info={} 预置同款，防 except 收尾路径 NameError）。
- [x] 1.2 core/agent_runner/runner.py：非成功终态的 _log_run_metrics 调用点（现 16 处，仅成功路径 :5301-5306 透传）经公共 helper 透传 latency（_run_agent 返回 5 元组第 5 元素已在收尾作用域；_run_agent 之前早退的调用点无样本上下文，走零样本回退）；:9111/:9145-9147 零样本回退保持不变。

## 2. 升级信号与受控重试

- [x] 2.1 core/admin_monitor.py：AdminMonitor 检测面新增 api_round_stall_escalated 信号（merge_signal，dedup 键对 spec=null 周期 run 以 run_id 进 hash 位，单 run 至多一条）。检测数据源用 run jsonl 终态 run_metrics 行的 latency_max（_run_agent 收尾已写真实值，runner.py:7181-7183/:7227-7229；dsh 投影 0 样本行 latency_max=None 天然不触发，勿混入本 SPEC——属 86de1c7071b6 管辖），升级判据 latency_max > STALL_ROUND_ESCALATE_SECONDS（core/agent_runner/latency.py:43，与 classify_round_stall 单源）；节拍位置镜像 _check_code_review_stall（admin_monitor.py:2383）。
- [x] 2.2 core/agent_runner/result_gate.py：CodeReviewResult（:367）增 stall_redispatch 意图字段（缺省 None，形态对齐 :398-403 ratelimit_redispatch 先例）。
- [x] 2.3 core/agent_runner/maintenance_runs.py：run_code_review 车道收尾检测「warning-escalated 且 run 收尾 error（含硬门拒绝）」时登记 stall_redispatch 意图（warning-escalated 收尾判据：stats["max"] > STALL_ROUND_ESCALATE_SECONDS，5 元组 stats 无 grade 键、grade_counts 两级合桶且不入信封，故按 max 推导并与分级纯函数单源；复用现 :2413-2435 ratelimit 意图登记形态、经 :2464 结果信封上交；与 ratelimit 意图互斥，同 run 双条件时 ratelimit 优先——429 有明确 provider 归因，停滞归因仍是假设；上限 1 次/monitor 生命周期）。先抢救后重派的顺序由既有收尾结构（硬门 :3304-3315 → error 收场抢救落账 :2331-2392 → 意图登记 :2413-2435）保证，无需新增机制；原稿「zero_row 意图」无对应实现，互斥对象仅 ratelimit 意图。
- [x] 2.4 core/admin_monitor.py：消费 stall 意图（复用冷却+单飞骨架：上限守卫 :2140/:2153、单 Timer 守卫 :2160、冷却解析 :2174-2177、夜间窗顺延 :2289-2300，按意图类型分发），以 redispatch_of 链重派一次（复用 :2356 链路）；runner.py:6471 与 :7045-7046 注释按新行为更新（「运行中不触发」约束不变，指向收尾后 AdminMonitor 信号面）。

## 3. 留痕

- [x] 3.1 core/agent_runner/runner.py：api_round_stall 日志 context（_stall_ctx，现 :6492-6499）补当轮上下文规模（input tokens）与 provider 字段。

## 4. 测试

- [x] 4.1 tests/test_api_stall_disposition.py：error 终态 run_metrics 的 latency_* 与过程指标一致；成功终态透传不回归；无停滞 run 行为零变化；_run_agent 抛出路径收尾 latency 走零样本且不 NameError。
- [x] 4.2 tests/test_api_stall_disposition.py：warning-escalated→信号 1 条且同 run 去重；「warning-escalated 且收尾 error」→stall 意图登记/上限 1 次/与 ratelimit 互斥且双条件 ratelimit 优先/redispatch_of 指向原 run；「曾停滞但正常完成」→无信号无意图。
