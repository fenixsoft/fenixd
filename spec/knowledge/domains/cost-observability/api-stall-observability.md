# Run 期 API 往返停滞观测与入账

<!-- knowledge: capability=api-stall-observability rev=2
     sources=spec/archive/2026-10-07-evo-add-api-stall-observability,spec/archive/2026-10-30-evo-api-stall-signal-grading -->

run 期内单次 API 往返停滞的分级记录与结构化入账：超长往返按严重度分级留现场信号，停滞计数与最长间隔随 run_metrics 持久化并进每日自省摘要，形成可按 run/provider 聚合的长期基线；全部动作纯读侧，不做任何干预。

## 规则

- **期内停滞分级信号**：在飞延迟采样点（样本口径 = tool_result→下一 assistant 间隔，与 run-latency-observability 同源单点）对单轮延迟超过 `STALL_ROUND_WARN_SECONDS = 120.0` 秒的样本分级（事件名恒为 api_round_stall，context 增 `grade` 字段）：单轮 >120s 且 ≤300s、且非连续第 2 轮及以上停滞 → INFO 级落日志（`grade="info"`，只计数）；连续 2 轮及以上停滞（连续 = 相邻样本逐个 >120s，遇 ≤120s 样本重置计数）→ WARNING（`grade="warning"`）；单轮 >300s（`STALL_ROUND_ESCALATE_SECONDS`）→ WARNING（`grade="warning-escalated"`）。阈值内样本零信号（严格 > 判定，≤120s 含 119.9s 边界样本静默）；timestamp 缺失/负差值等无效测量既不产样本也不触发信号。
- **停滞常量语义分离**：四常量同值（或近值）不同义、各自独立，严禁合并、复用或互相引用——`STALL_ROUND_WARN_SECONDS = 120.0`（期内分级告警线）、`STALL_ROUND_ESCALATE_SECONDS = 300.0`（单轮升级线，独立声明、不并入既有常量同源组）、`LATENCY_STALL_SECONDS = 60.0`（停滞统计口径，深扫行/摘要日志/stall_ratio 分母依赖，改动破坏历史可比性）、`RUN_STALL_ROUND_SECONDS = 120.0`（run-stop-loss 判停样本计入线，行为面）；常量同源契约测试锁定既有三常量；告警线改动不得泄漏成判停行为变更。
- **run 级统计入账**：run 结束汇总行（`format_latency_summary` 渲染）行尾附分级计数（`warning=N info=M`；既有 stalls>60s 口径不变）。run 收尾时，档案 run_metrics 行（`append_run_line` 的 `type: run_metrics`）与 daemon 侧 run metrics 结构化日志（`metric_type: run_metrics`）均含 `latency_rounds`（有效样本数）、`latency_stalls`（>60s 样本数）、`latency_max`（最长样本秒）三字段，取值复用 run 末延迟摘要已计算的同一 `latency_stats` 结果——单一真源，禁止重复采样或二次计算。**成功终态**的 run metrics 日志行必须带本 run 实际三字段（统计对象经主通道返回值随 `_finalize_success` 传入），MUST NOT 回退 0/0/None；提前终态路径（无样本上下文）维持零样本回退（`latency_rounds=0`、`latency_stalls=0`、`latency_max=None` 或省略 latency_max），不抛异常、不阻断 run 收尾；轮询环崩溃路径下 run_metrics 行仍照既有契约追加，字段缺省不抛。
- **每日自省停滞聚合**：每日自省数据摘要第 6 节含「API 停滞聚合」——当日 stall 计数>0 的每个 run 列 run_id、stall 次数、累计停滞秒、最大单轮秒；三值同源自 `latency_samples_from_events` 产出的 samples（stalls/max 取 >60s 统计口径，累计停滞秒取 >60s 样本之和）；聚合随第 6 节既有降级契约（聚合环节异常降级空产出 + warning，不阻断摘要与其余各节）；逐 run 扫描沿用既有有界流式口径（`MIDFLIGHT_SCAN_MAX_LINES` 上限、逐行解析，MUST NOT 整文件读入内存）；不改 MIDFLIGHT_OUTLIER_DIMS 既有三维度与深扫行为。
- **行序契约不变**：run jsonl 仍恰一条 run_metrics 行且位于终态行之后、末行=终态；停滞记录不向 jsonl 注入任何新事件类型，事件类型集合与无停滞记录时一致。
- **纯读侧不干预**：全部记录动作不改变流式事件处理时序、不终止/重启进程、不重派、不接入独立人工告警与 admin 唤醒、不新增配置键。run 终态（success/failure）与调度不因停滞记录改变；既有 run-stop-loss 判停按其自身判据独立评估，不受本能力影响亦不被本能力豁免。

## 关键行为

数据流两段：① 在飞采样点逐样本分级——info 只计数、warning/warning-escalated 打 WARNING 留现场；② run 末 `latency_stats` 单次计算，分级计数进汇总行、三字段进 run_metrics 两落点（持久化基线）。消费面：每日自省第 6 节聚合行提供 run 级可见性——停滞但 turns/cost_usd/duration 三维度正常的 run 不再漏出深扫初筛；dashboard 增量索引按 `metric_type==run_metrics` 读特定键，加法字段无破坏。

## 溯源

- 2026-10-07 evo-add-api-stall-observability（spec/archive/2026-10-07-evo-add-api-stall-observability） — 新增本能力：期内停滞时点记录（告警线/统计口径/判停线三常量语义分离）、latency_rounds/latency_stalls/latency_max 三字段随 run_metrics 两落点入账、零样本与崩溃路径安全回退、纯读侧不干预纪律
- 2026-10-30 evo-api-stall-signal-grading（spec/archive/2026-10-30-evo-api-stall-signal-grading） — 修订：stall 信号分级（120-300s 单轮降 INFO 只计数、连续 ≥2 轮停滞或单轮 >300s 才 WARNING，新升级常量独立声明、既有三常量不动）、run 末汇总行附分级计数、成功终态 run_metrics 日志行补传实际三字段（消除无样本上下文的 0/0/None 回退误伤）、每日自省第 6 节新增 API 停滞聚合行（动因实测：WARNING 已常态化失敏——5 日 145 条零处置零升级，单轮最长 514.3s、样本 run 总时长 4-5 倍化）
