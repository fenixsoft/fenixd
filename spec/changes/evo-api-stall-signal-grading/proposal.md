# 提案：api-stall-signal-grading

## 背景与动机

agent_runner 对单轮超过 120 秒的 API 往返打 WARNING（事件 api_round_stall，发射点 core/agent_runner/runner.py:6184-6198，阈值常量 STALL_ROUND_WARN_SECONDS=120.0 位于 core/agent_runner/latency.py:36，硬编码、无 config 覆盖）。该信号自 2026-10-07-evo-add-api-stall-observability 引入后已常态化失敏：

- 近 5 日（2026-10-10 至 10-14）两份 daemon 日志合计 145 条（fenixd 主日志 118 条 + potplayer 项目日志 27 条），单日最多 55 条（10-13），横跨 8 类 run 前缀；
- 样本 run code-review-1791997236（2026-10-14）：两轮停滞 337.2s+192.4s=529.6s，占 606.6s 总时长 87.3%，其后修复链推迟约 9 分钟；单轮最长 514.3s（2026-10-12 code-review-1791824535 round#1，首轮即停滞）；
- WARNING 零处置零升级：run-stop-loss 判停通道存在（runner.py:6399-6430）但 RUN_STALL_BUDGET_ENABLED_DEFAULT=False（core/config.py:381）且两项目 config.yaml 均未启用；
- 每日自省数据摘要第 6 节只对初筛离群 run 深扫（初筛维度 MIDFLIGHT_OUTLIER_DIMS=turns/cost_usd/duration_seconds，core/self_review.py:774，不含 stall），停滞但三维度正常的 run 不出现——相关停滞靠手工 grep 日志才发现。

时间实损已量化发生（145 次 × 每次 120-514 秒轮次阻塞；样本 run 总时长 4-5 倍化），非假设风险。金额损失为零，损失面是 run 墙钟时长与探测信号有效性。

## 方案概述

只做读侧（观测面）两件事，不新增任何自动干预：

1. stall 信号分级：单轮 120-300 秒降为 INFO 只计数；连续 2 轮及以上超 120 秒或单轮超 300 秒才打 WARNING；run 结束汇总行附分级计数；成功终态 run metrics 日志行补传 stall 统计（run 档案 jsonl 行已持久化 latency 三字段，仅终态日志行经 _log_run_metrics 回退 0/0/None）。
2. 每日自省数据摘要第 6 节新增 run 级停滞聚合行：当日 stall 计数>0 的 run（run_id、stall 次数、累计停滞秒、最大单轮秒），数据复用 latency_samples_from_events/latency_stats。

## 非目标

- 不新增配置键（沿用既有硬编码常量约定）；
- 不改动 LATENCY_STALL_SECONDS / STALL_ROUND_WARN_SECONDS / RUN_STALL_ROUND_SECONDS 三常量的取值与语义（遵守 2026-10-07-evo-add-api-stall-observability 的「同值不同义，严禁合并复用」裁定）；
- 不做换道重试/自动干预（run-stop-loss 判停面保持现状；多 provider 换道属未来独立立项）。