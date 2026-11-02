# 能力：api-stall-disposition（API 停滞处置闭环）

## 术语

- warning-escalated：api_round_stall 分级中需升级关注的档位（分级纯函数 core/agent_runner/latency.py，10-15 evo-api-stall-signal-grading 落地）。收尾侧等价判据：stats["max"] > STALL_ROUND_ESCALATE_SECONDS（latency.py:43）——5 元组 stats 不携带 grade 键，收尾判定按此推导并与分级纯函数单源。
- 受控重试：车道收尾后登记 stall_redispatch 重派意图，由 AdminMonitor 冷却+单飞消费的至多一次重派；不与「运行中重试」混淆。

## 需求

1. 终态 latency 透传：_log_lane_run_metrics（core/agent_runner/maintenance_runs.py:1306-1348）签名增加 latency 参数（缺省 None）并在全部车道收尾调用点（:564/:927/:1671/:2440/:3339）传入 _run_agent 返回的 stall stats（:387/:854/:1462/:2083/:3248 五处解包的 _stall_latency；各车道 try 前预初始化 None，_run_agent 抛出路径按零样本语义）；core/agent_runner/runner.py 内非成功终态的 _log_run_metrics 调用点（现 16 处仅成功路径 :5301-5306 透传）经公共 helper 同步透传，:9111/:9145-9147 零样本回退保持。
2. 升级信号：warning-escalated 经 AdminMonitor 检测面（镜像 admin_monitor.py:2383 _check_code_review_stall 既有零进度探测的节拍模式；检测数据源用 run jsonl 终态 run_metrics 行的 latency_max，runner.py:7181-7183/:7227-7229）写 merge_signal，signal_type=api_round_stall_escalated；dedup 键 (spec, signal_type, hash) 对周期 run spec=null 时以 run_id 进 hash 位（core/admin_store.py:611/:694-699 键形态），同 run 不重复落信号。
3. 受控重试：run_code_review 车道收尾检测「warning-escalated（按 stats["max"] > STALL_ROUND_ESCALATE_SECONDS 判定）且 run 收尾 error（含硬门拒绝）」时登记 stall_redispatch 意图（复用 maintenance_runs.py:2413-2435 ratelimit 意图登记形态、经 :2464 结果信封上交，信封字段落在 core/agent_runner/result_gate.py CodeReviewResult），admin_monitor 冷却+单飞消费，上限 1 次/monitor 生命周期，与 ratelimit 意图互斥（同 run 双条件时 ratelimit 优先——429 有明确 provider 归因，停滞归因仍是假设）；先抢救后重派的顺序由既有收尾结构（硬门 :3304-3315 → 抢救落账 :2331-2392 → 意图登记 :2413-2435）保证；对「曾停滞但正常完成」的 run 不重试。
4. 留痕：api_round_stall 日志 context（_stall_ctx，runner.py:6492-6499）补当轮上下文规模（input tokens）与 provider 字段。
5. 注释一致性：runner.py:6471「不 kill、不重派、不触发人工告警」与 :7045-7046「延迟数据不触发独立人工告警铁律」按新行为更新表述（运行中路径不触发的约束不变；信号由收尾后 AdminMonitor 检测面写，不新增运行中打断）。

## 验收

- 构造 error 终态 run：终态 run_metrics 的 latency_* 与过程指标一致（非 0/0/null）；成功终态透传不回归（:5301-5306 既有路径）；_run_agent 抛出路径收尾 latency 零样本且不 NameError。
- 构造 warning-escalated：admin 信号面出现 1 条，同 run 第二次升级不新增。
- 构造「warning-escalated 且收尾 error」：stall 意图登记且上限 1 次，与 ratelimit 意图互斥且双条件 ratelimit 优先，重派 manifest 带 redispatch_of。
- 「曾停滞但正常完成」的 run：无信号、无重试意图。
