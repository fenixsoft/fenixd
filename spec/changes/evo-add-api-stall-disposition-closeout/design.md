# 设计：add-api-stall-disposition-closeout

## 关键决策

1. 双链路同修：终态行有两条产生链（runner.py 内 16 个 _log_run_metrics 调用点 vs maintenance_runs.py _log_lane_run_metrics 车道收尾咽喉），本窗 error 终态只可能来自后者；在途 evo-api-stall-signal-grading「只修成功终态」的半修教训表明必须两条链一起收口——抽公共透传 helper，避免散改漂移。
2. 重试落车道层不落发射点：发射点在 _run_agent 深处，直接重试会与 attempt 循环、默认关闭的 run-stop-loss 判停通道（runner.py:6455-6463 stall_cfg 门控的判停采样通道）互踩；车道层已有 ratelimit_redispatch 意图先例（maintenance_runs.py:2413-2435 登记、:2464 结果信封上交），stall 意图复用同骨架并互斥。
3. 重试触发条件收窄：只对「warning-escalated 且 run 收尾 error」登记意图——停滞本质是 provider 长尾延迟，对最终成功的 run 重试是纯浪费；停滞致败（含叠加零产物硬门拒绝）才值得救。与既有收尾顺序的语义（产物硬门 maintenance_runs.py:3304-3315 → error 收场抢救落账+writeoff 锚 :2331-2392 → 重派意图登记 :2413-2435）：先抢救、抢救尽才轮到重派意图——该顺序由收尾代码结构保证，无需新增机制（原稿所引「zero_row 意图 / evo-add-review-lane-toolface-guard」在代码、spec/archive、git 历史中均不存在，已修正为真实机制引用）；同一原 run 同时只允许一类在途意图，同 run 双条件（429 归因且停滞升级）时 ratelimit 意图优先——429 有明确 provider 归因，停滞归因仍是假设。
4. 信号与铁律的关系：「延迟数据不触发独立人工告警」铁律（runner.py:7045-7046）约束的是 runner 运行中路径；本 SPEC 的信号在 run 收尾后由 AdminMonitor 检测面写（镜像 admin_monitor.py:2383 _check_code_review_stall 零进度探测的节拍模式；检测数据源用 run jsonl 终态 run_metrics 行的 latency_max，runner.py:7181-7183/:7227-7229），不破铁律、不新增运行中打断——两处注释同步改写防止注释与实现矛盾。
5. 去重键：周期评审 run 无 spec 归属，merge_signal 的 (spec, signal_type, status_hash) 键（admin_store.py:611/:694-699）对 spec=null 需以 run_id 进 hash 位，避免同窗多轮停滞刷屏（单 run 至多一条）。
6. 风险：受控重试在 provider 持续长尾时可能重演停滞——上限 1 次+冷却即止损边界；留痕字段（上下文规模/provider）为后续跨日归因供数，本 SPEC 不做归因裁决。