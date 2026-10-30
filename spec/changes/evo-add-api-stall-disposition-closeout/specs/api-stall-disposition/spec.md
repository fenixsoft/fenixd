# 能力：api-stall-disposition（API 停滞处置闭环）

## 术语

- warning-escalated：api_round_stall 分级中需升级关注的档位（分级纯函数 core/agent_runner/latency.py，10-15 evo-api-stall-signal-grading 落地）。
- 受控重试：车道收尾后登记 stall_redispatch 重派意图，由 AdminMonitor 冷却+单飞消费的至多一次重派；不与「运行中重试」混淆。

## 需求

1. 终态 latency 透传：_log_lane_run_metrics（core/agent_runner/maintenance_runs.py:1195-1247）签名增加 latency 参数并在全部车道收尾调用点（:474/:812/:1544/:2304/:3188）传入 _run_agent 返回的 stall stats（现 :1952 解包后弃用的 _stall_latency）；core/agent_runner/runner.py 内非成功终态的 _log_run_metrics 调用点（现 16 处仅成功路径 :5255 透传）经公共 helper 同步透传，:9063-9065 零样本回退保持。
2. 升级信号：warning-escalated 经 AdminMonitor 检测面（镜像 :2291 既有零进度探测的节拍模式）写 merge_signal，signal_type=api_round_stall_escalated；dedup 键 (spec, signal_type, hash) 对周期 run spec=null 时以 run_id 进 hash 位（core/admin_store.py:573 键形态），同 run 不重复落信号。
3. 受控重试：车道收尾检测「warning-escalated 且 run 收尾 error（含硬门拒绝）」时登记 stall_redispatch 意图（复用 :2280-2298 附近 ratelimit 意图落盘形态），admin_monitor 冷却+单飞消费，上限 1 次/monitor 生命周期，与 ratelimit/zero_row 意图互斥；对「曾停滞但正常完成」的 run 不重试。
4. 留痕：api_round_stall 日志 context 补当轮上下文规模（input tokens）与 provider 字段。
5. 注释一致性：runner.py:6404-6406「不触发人工告警」与 :6963-6969「延迟数据不触发独立人工告警铁律」按新行为更新表述（信号由收尾后 AdminMonitor 检测面写，不新增运行中打断）。

## 验收

- 构造 error 终态 run：终态 run_metrics 的 latency_* 与过程指标一致（非 0/0/null）；成功终态透传不回归（:5255 既有路径）。
- 构造 warning-escalated：admin 信号面出现 1 条，同 run 第二次升级不新增。
- 构造「warning-escalated 且收尾 error」：stall 意图登记且上限 1 次，与 ratelimit/zero_row 意图互斥，重派 manifest 带 redispatch_of。
- 「曾停滞但正常完成」的 run：无信号、无重试意图。