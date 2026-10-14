# 能力：api-stall-observability —— stall 信号分级与摘要可见性

## 需求

### R1 stall 分级

- 单轮延迟 >120 秒且 ≤300 秒、且非连续第 2 轮及以上停滞：以 INFO 级落日志，事件名仍为 api_round_stall，context 增 grade="info"，只计数、不打 WARNING。
- 连续 2 轮及以上停滞（各轮 >120 秒），或单轮 >300 秒：打 WARNING，context 增 grade 字段（连续停滞 grade="warning"、单轮超限 grade="warning-escalated"）。
- 分级阈值以新常量表达（STALL_ROUND_ESCALATE_SECONDS=300.0），不复用、不改值三既有常量（LATENCY_STALL_SECONDS=60.0 统计线、STALL_ROUND_WARN_SECONDS=120.0 告警线、RUN_STALL_ROUND_SECONDS=120.0 判停线）。

### R2 run 级停滞统计入账

- run 结束汇总行（format_latency_summary 渲染）附分级计数（warning=N info=M）。
- 成功终态的 run metrics 日志行（_log_run_metrics）必须带本 run 实际 latency_rounds/latency_stalls/latency_max，不得回退 0/0/None；run 档案 jsonl 行既有字段不变。

### R3 每日自省摘要可见性

- core/self_review.py collect_daily_summary 第 6 节新增「API 停滞聚合」行：当日 stall 计数>0 的每个 run 列 run_id、stall 次数、累计停滞秒、最大单轮秒；不改动 MIDFLIGHT_OUTLIER_DIMS 既有三维度与深扫行为。

## 约束

- 纯读侧：不新增自动干预、不 kill 进程、不换道、不新增配置键。
- 三常量取值与语义不动；tests/test_agent_runner_modules_contract.py 的常量同源契约不破。