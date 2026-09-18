# 设计：自省聚合窗口快照

## Context

core/self_review.py:110-111 `_in_window` 用 `datetime.now()` 作上界，collect_runs_stats（:180）与 agent_runner 派发并行时，聚合中段新创建的 run 文件可能漏计。实证：scheduling-showcase 09-11 自省把 2 个盲跑 run 计为 1 个。

## Goals / Non-Goals

- **Goals**：聚合结果与聚合启动时点的磁盘状态一致；边界确定性可复现。
- **Non-Goals**：不改变聚合口径语义（仍 [window_start, 聚合时点]）；不引入调度侧『先聚合后派发』依赖（侵入调度时序）。

## Decisions

### D1：快照在聚合函数入口冻结

**选择**：collect_runs_stats / collect_log_errors 入口取 `window_end = datetime.now()`，改 _in_window 签名接收 window_end 参数（默认缺省实时 now 以兼容既有调用方）。

**理由**：最小侵入；不依赖调用时序；确定性可测（构造边界时间戳断言归属）。

### D2：快照一次贯穿全部判定

**选择**：同一聚合内所有 run 判定共用同一 window_end，聚合中途新增 run 文件不回流。

**理由**：保证『聚合结果 = 聚合启动时点磁盘快照』语义完整。