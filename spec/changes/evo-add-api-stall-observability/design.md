# Design: add-api-stall-observability

## Context

复核条目「API停滞缺观测与重试」已核实：停滞采样与统计能力在飞（`core/agent_runner/runner.py:4841-5002` 内联旁路、`:5364-5377` run 末摘要日志）与离线（`core/self_review.py:880-945` `_scan_run_midflight` 深扫重算）均已存在，阈值 `LATENCY_STALL_SECONDS=60.0`（`core/agent_runner/latency.py:22`）。缺口仅在：统计结果不进档案 run_metrics 记录（写入点 `runner.py:5427-5440`）与 daemon 侧 run metrics 日志（`:6807-6829`），且期内无逐次时点记录。run 为 claude CLI 子进程（`runner.py:4`、`:675`），框架对子进程内 API 请求不可干预——「原地重试/重连」越界，本 SPEC 不做。

## Goals

- 停滞指标结构化入账，形成可按 run/provider 聚合的长期基线。
- 单次超长往返有期内时点记录（WARNING 日志），补足「只有聚合无现场」。

## Decisions

1. **阈值与统计阈值分离**：新增 `latency.py` 模块级常量 `STALL_ROUND_WARN_SECONDS = 120.0`，不动 `LATENCY_STALL_SECONDS=60.0`。前者是期内告警线，后者是既有统计口径（深扫行、摘要日志、stall_ratio 分母均依赖它），改动会破坏历史可比性。同值警示：`runner.py:172` 既有 `RUN_STALL_ROUND_SECONDS = 120.0`（run-stop-loss 判停判据一的样本计入线）与新常量**同值不同义**，实现须另立常量、禁止合并复用——判停线属行为面，改动不在本 SPEC 范围。
2. **WARNING 落在样本完成时点而非计时器看门狗**：在既有内联采样点（样本入列处，`runner.py:4995-5002` 邻域）对完成样本判阈值。不做「无事件 N 秒」实时定时器——读循环阻塞语义下需新增线程/超时机制，而框架反正不会对停滞做期内干预（决策 4），时点价值有限、复杂度不成比例。
3. **入账复用同一 stats 单一真源**：run 末延迟摘要已在 `runner.py:5364-5377` 调 `latency_stats`；各指标落点直接引用同一结果对象，禁止二次采样（两处口径漂移是既有事故形态，见 `tool-result-stream-detection`）。daemon 侧结构化日志实际存在**两个形态**，都须补字段：`_run_claude` 正常收尾内联日志（约 5440-5457，与档案行同段、不经过 `_log_run_metrics`，直接复用同一 stats）与通用方法 `_log_run_metrics`（约 6787-6832，调用点全在 `_run_claude` 之外——run_planner/_prepare_worktree/_attempt_top_guards/_finalize_success/_resolve_provider_candidate/_exhausted_result 等提前终态路径，无样本上下文），后者以可选参数承接、调用侧未持样本时按零样本回退（0/0/None）。
4. **显式不做干预**：不 kill、不重派、不接人工告警。依据：(a) CLI 子进程黑盒，框架无从重连；(b) 合法长轮与真停滞转录不可区分（2026-10-02 窗口实证：对照 run 亦有 119s 空隙、目标 run 4 个 stall 中 3 个在 85–123s）；(c) 过早重试放大 token 消耗。
5. **不向 run jsonl 注入新事件类型**：档案行序/行数有多处契约消费者（末行=终态、恰一条 run_metrics、深扫 error/stderr 计数），日志侧 WARNING 已可检索，避免扩散契约面。

## Risks

- **字段加法被未知的严格 schema 消费者拒绝**：已核 `tests/test_daemon_lifecycle_races.py:448` 契约只锁行数与行序不锁字段集合；dashboard 按 `metric_type==run_metrics` 增量索引读特定键，加法字段无破坏。缓解：验收场景断言新字段在场同时既有字段不动。
- **WARNING 频繁刷屏**：单 run 最多 rounds 条。实测窗口最差 4 条/run，量级无害；不做节流，保持现场完整。
- **零样本/崩溃路径回退**：`latency_stats` 空样本已安全返回 0/None（`latency.py` `latency_stats` base 分支），崩溃路径 run_metrics 照写是权威测试锁定的契约形态（`runner.py:5414-5423` 注记），字段缺省须走同一 try 兜底。
- **与既有 run-stop-loss 并存**：同一采样点已有 `_stall_budget_record_sample` 旁挂（`runner.py:5006`，evo-add-run-stop-loss），按 `RUN_STALL_ROUND_SECONDS=120` 累积判停样本（`_stall_budget_config` 缺省关闭，启用后由轮询环独立评估判停）。本能力为纯读侧记录，不读不写 stall budget 状态、不影响其评估；验收断言限定「本能力的记录动作不触发干预」，既有判停按其自身判据独立生效、不被本能力豁免。