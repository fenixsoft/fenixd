# Proposal: add-api-stall-observability

## Why

2026-10-02 potplayer-base 的 planner-judge run（1790925014-a1）出现 4 次 >60s 的 API 往返停滞（最长 251.1s），run 总时长 897.5s（同组 4 条 judge run 中位 283.7s 的 3.16 倍）。停滞数字目前只存在于 run 末一条独立 INFO 日志（`fenixd.log: "run …: 17 rounds, … stalls>60s=4 (24%)"`），既不进档案 run_metrics 记录、也不进 daemon 侧 run metrics 结构化日志，导致：

- 长期无法按 run/按 provider 聚合停滞基线（每日深扫只能对离群 run 重读事件流重算）；
- run 期内单次超长往返无任何时点记录，事后只有聚合数、无逐次现场。

已核实边界：run 是 claude CLI 子进程（`core/agent_runner/runner.py` "Spawns claude CLI subprocesses"），单次 API 往返发生在子进程内，框架不可重连、不可原地重试；合法长轮与真停滞在 stream-json 转录上不可区分（对照 run 亦有 119s 空隙）。因此本 SPEC **只做记录与入账，不做任何自动干预**（不 kill、不重派、不触发人工告警——沿用 run-latency-observability 既有告警纪律）。

## What Changes

- 在飞采样点（`_run_claude` 流式循环旁路，样本 = tool_result→assistant 间隔）对超过新阈值 `STALL_ROUND_WARN_SECONDS=120s` 的单次样本即时打一条 WARNING 日志（含 run_id、样本秒数、轮序）。
- run 收尾两处指标落点（档案 run_metrics 行、daemon 侧 run metrics 结构化日志）各增 `latency_rounds` / `latency_stalls` / `latency_max` 三个字段，复用既有 `latency_stats` 结果，禁止二次计算。
- 无行为变更：不改流式时序、不改终态/收尾行序契约、不加配置面、不做重试。

## Capabilities

### New Capabilities

- `api-stall-observability`: run 期内单次 API 往返停滞的时点 WARNING 记录，与停滞计数/最长间隔随 run_metrics 的结构化入账。

### Modified Capabilities

（无——run-latency-observability 的采样口径、摘要格式、告警纪律均不变，本能力只在其上追加记录通道。）

## Impact

- 代码：`core/agent_runner/latency.py`（新常量）、`core/agent_runner/runner.py`（WARNING + 两处指标落点补字段）。
- 测试：`tests/test_run_latency_stats.py`（扩展）、`tests/test_run_stall_accounting.py`（新增）。
- 消费面：每日深扫（`core/self_review.py`）可逐步改读持久化字段（本 SPEC 不强制改造读侧，留作后续）；dashboard 增量索引按 `metric_type==run_metrics` 读特定键，加法字段无破坏。