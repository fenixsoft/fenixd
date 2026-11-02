# 合并增量（2026-10-30 人工全量核查）

折叠条目：3b79afb80a10、451ff3723c2a、d8f837f5ba92、58fecfe79be2（potplayer-base 同根因并入）。

- 两断点复核成立：①runner.py:6483-6512 停滞升级只落日志零 admin 信号（发射点注释「不触发人工告警」须显式修订；复用 instant_fail_storm 的 throttle＋latest_signal 查重模式，runner.py:8396-8434 现成模板）；②maintenance_runs.py:1306 `_log_lane_run_metrics` 无 latency 形参、五调用点解包 `_stall_latency` 后弃用（调度车道半边已由 evo-api-stall-signal-grading 1.3 修掉，本 SPEC 承接维护车道残差＋零样本回退 `or 0` 语义）。
- 吸收 d8f8：`_stall_ctx`（runner.py:6493-6497）增 provider/当轮规模等归因字段——「升级零处置」与「归因缺失」一并治。
- 58fe 的「轮级重发」列为非目标（政策分歧：归因先行、重试缓行；与 evo-add-run-stop-loss 判停机制分界；停滞本体 10-23 起 6 窗零复发系 provider 长尾环境缓解）。
- 边界注记：dsh-harness 投影无时间戳致生产面 0 样本是第三种机制（86de1c7071b6 add-dsh-events-latency-timestamps 管辖）——勿混入本 SPEC；本 SPEC 落地后 dsh run 的停滞取证才恢复可执行（单向依赖）。
