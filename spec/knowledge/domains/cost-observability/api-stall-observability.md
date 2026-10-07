# Run 期 API 往返停滞观测与入账
<!-- knowledge: capability=api-stall-observability rev=1
     sources=spec/archive/2026-10-07-evo-add-api-stall-observability -->

run 期内单次 API 往返停滞的时点记录与结构化入账：超长往返在发生时点留 WARNING 现场，停滞计数与最长间隔随 run_metrics 持久化，形成可按 run/provider 聚合的长期基线；全部动作纯读侧，不做任何干预。

## 规则

- **期内停滞时点 WARNING**：在飞延迟采样点（样本口径 = tool_result→下一 assistant 间隔，与 run-latency-observability 同源单点）对单次样本超过 `STALL_ROUND_WARN_SECONDS = 120.0` 秒的，在该样本完成时点（非 run 收尾）即时输出一条 WARNING 日志（component=agent_runner，event=api_round_stall），含 run_id、样本秒数（1 位小数）与轮序号（该样本在有效样本序列中的序数）。阈值内样本零 WARNING（严格 > 判定，≤120s 含 119.9s 边界样本静默）；timestamp 缺失/负差值等无效测量既不产样本也不触发 WARNING。
- **告警不改统计**：触发 WARNING 的样本照常进入既有样本序列，`latency_stats` 结果与不加告警时逐字段一致。
- **停滞指标随 run_metrics 入账**：run 收尾时，档案 run_metrics 行（`append_run_line` 的 `type: run_metrics`）与 daemon 侧 run metrics 结构化日志（`metric_type: run_metrics`）均含 `latency_rounds`（有效样本数）、`latency_stalls`（>60s 样本数）、`latency_max`（最长样本秒）三字段，取值复用 run 末延迟摘要已计算的同一 `latency_stats` 结果——单一真源，禁止重复采样或二次计算。daemon 侧该日志存在 `_run_claude` 正常收尾内联形态与通用方法 `_log_run_metrics`（提前终态路径调用，如 run_planner/prepare_worktree/finalize_success 等）两个形态，两形态都必须带字段。
- **零样本与崩溃路径回退**：run 无任何有效样本（启动即失败/解析器零配对）时三字段回退 `latency_rounds=0`、`latency_stalls=0`、`latency_max=None`（或省略 latency_max），不抛异常、不阻断 run 收尾；`_log_run_metrics` 调用侧未持样本上下文时按同一零样本回退。轮询环崩溃路径下 run_metrics 行仍照既有契约追加，字段缺省不抛。
- **行序契约不变**：run jsonl 仍恰一条 run_metrics 行且位于终态行之后、末行=终态；停滞记录不向 jsonl 注入任何新事件类型，事件类型集合与记录前一致。
- **停滞常量语义分离**：三常量同值不同义、各自独立，严禁合并、复用或互相引用——`STALL_ROUND_WARN_SECONDS = 120.0`（期内告警线，单源定义于 `core/agent_runner/latency.py`，runner re-export 同值）、`LATENCY_STALL_SECONDS = 60.0`（停滞统计口径，深扫行/摘要日志/stall_ratio 分母依赖，改动破坏历史可比性）、`RUN_STALL_ROUND_SECONDS = 120.0`（run-stop-loss 判停样本计入线，行为面）；告警线改动不得泄漏成判停行为变更。
- **纯读侧不干预**：全部记录动作不改变流式事件处理时序、不终止/重启进程、不重派、不接入独立人工告警与 admin 唤醒、不新增配置键。run 终态（success/failure）与调度不因停滞记录改变；既有 run-stop-loss 判停按其自身判据独立评估，不受本能力影响亦不被本能力豁免。

## 关键行为

数据流两段：① 在飞采样点逐样本判 120s 阈值打 WARNING（期内现场）；② run 末 `latency_stats` 单次计算，同一结果写档案 run_metrics 行与 daemon 侧结构化日志（持久化基线）。消费面：每日深扫对离群 run 仍按自身口径重读事件流重算，可逐步改读持久化字段；dashboard 增量索引按 `metric_type==run_metrics` 读特定键，加法字段无破坏。

## 溯源

- 2026-10-07 evo-add-api-stall-observability（spec/archive/2026-10-07-evo-add-api-stall-observability） — 新增本能力：期内停滞 WARNING 时点记录（120s 告警线与统计口径/判停线三常量语义分离）、latency_rounds/latency_stalls/latency_max 三字段随 run_metrics 两落点入账、零样本与崩溃路径安全回退、纯读侧不干预纪律。
