# 合并增量（2026-10-30 人工全量核查）

折叠条目：6dc7344f369f（dsh-plugins 实例；其 .fenix/core→/root/fenixd/core symlink，三缺口全落本仓框架代码）。

- 6dc7 增量并入为附加任务：①spawn 后写工具预检（agent_runner 全仓现无 allowedTools 预检，grep 零命中）；②终局消息结论行抢救（maintenance_runs.py:2331-2354 error 收场只读 shard_paths/主产物文件，结论丢失）；③run_metrics 工具面留痕。
- 主修面不变：maintenance_runs.py:2131-2143 gate_err 分支透出结构化失败类别＋admin_monitor 复用 ratelimit_redispatch 骨架（:1454-1460，RATELIMIT_REDISPATCH_MAX=1 同款限次）拦截后重派 1 次、仍败升级 admin 信号；agents/code-review.md 补自救纪律（基础工具直调＋select: 精确名探测＋TOOLFACE-MISSING fail-fast）配契约测试（参照 tests/test_prompt_lane_efficiency_sections.py 先例）。
- 覆盖边界：evo-add-instant-fail-cooldown-full-lane-gate 管进程秒死（正交）；evo-add-review-night-defer-snapshot-writeoff 管窗避让/核销（互补）；evo-add-codefix-anomaly-redispatch-budget（10-30 归档，回归域重派预算）为相邻先例可引用；90fcabd7f5a6（code-fix 批链止损）**不并入**——止损方向相反（熔断停派 vs 拦截后主动重派），车道/代码面均不同。
