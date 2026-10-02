# Proposal: add-self-review-midflight-signals

## Why

自省对每个 run 只读尾 3 行做终态分类（`_read_run_tail(p, 3)`），看不到 run 中途发生的事：成功收尾的 run 可能中途经历大量空转轮次、API 停滞、出错后被编排层重试/换道救回——这类「过程性浪费与险情」全部漏检。实证：`code-fix-1790305282` 这类多轮 run 的中途 stderr/error 事件、fenixd.log 中 1546 条 retry/switch/gave up 编排痕迹，均不在自省五源摘要的任何一节中。自省因此系统性低估实际浪费，todo.md 缺失大量可立项条目。

## What Changes

- 新增**中途信号采集器**（第六数据源）：窗口内全部 run（含成功）扫描三类机械化信号——
  1. **量化离群**（run_metrics 初筛）：turns / cost_usd / duration_seconds 相对同 agent_type 窗口基线离群，成功 run 也入选；
  2. **事件流深扫**（仅离群 run）：复用 `core/agent_runner/latency.py` 纯函数（`latency_samples_from_events` / `latency_stats`），报告停滞（stall）计数与最长往返、中途 error/stderr 事件痕迹；
  3. **编排层救回痕迹**：fenixd.log 中 provider switched / retry / gave up / worktree 重建等关键词行，按窗口归集；
- 采集结果以新节「中途信号（含成功 run）」注入自省数据摘要（`collect_daily_summary`），自省 agent 据此产出 waste / mistakes / improvements 条目；
- 扫描策略 = **初筛 + 离群深扫**：全部 run 先经 run_metrics（日志索引，零事件流读取）量化初筛，仅对离群 run 深扫事件流（流式逐行、单行解析、有界内存）；
- 中途信号只进自省摘要，**不新增 admin 告警**（告警降噪铁律：合成兜底静默化）。

## Capabilities

### New Capabilities

- `self-review-midflight-signals`: 自省中途信号采集——窗口内全车道 run（含终态成功者）的中途浪费/险情机械化信号采集与摘要注入（量化离群初筛、离群 run 事件流深扫、编排层救回痕迹归集），含降级与降噪约束。

### Modified Capabilities

- （无：既有 `self-review` 能力的终态分类口径、五源摘要结构均不变；本能力以新增第六节接入，不改变任何既有 Requirement 行为。）

## Impact

- `core/self_review.py`：`collect_daily_summary` 增加第 6 节；新增中途信号采集函数（量化初筛 + 深扫编排 + 痕迹归集）；既有五源与 `_classify_run` 口径零改动。
- 复用（不改）：`core/agent_runner/latency.py`（`latency_samples_from_events` 接受生成器、`latency_stats`、`LATENCY_STALL_SECONDS`、`_entry_is_tool_result`）、`core/dashboard/data/runs.py`（run_metrics 索引访问器）。
- `agents/self-review.md`：数据摘要新增第六节说明与条目引导（中途信号作为 waste/improvements 证据来源）。
- `tests/test_self_review_midflight.py`（新增）：夹具化验证离群检测、深扫 stall/error 采集、痕迹归集、降级路径。
- 性能约束：事件流深扫流式逐行（单行可能数 MB），禁止整文件读入内存；深扫仅限离群 run，上限有界。
