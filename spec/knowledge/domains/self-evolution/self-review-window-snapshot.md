<!-- knowledge: capability=self-review-window-snapshot rev=1 sources=spec/archive/2026-09-18-evo-add-self-review-window-snapshot -->

# 自省聚合窗口快照

自省聚合的窗口上界在聚合启动时冻结一次，消除与 run 派发并行执行时的计数竞态。

## 现行规则

- 固定快照：自省聚合（run 统计 / 日志 ERROR 聚合）开始时对窗口上界取一次固定快照（`window_end = datetime.now()`），全部 `_in_window` 判定使用该快照值；聚合执行期间不再调用实时时钟判定窗口归属。
- 窗口语义为 `[window_start, window_end]` 闭区，仅上界取聚合启动时点冻结值。
- 并行派发不漏计：聚合启动后、完成前创建且时间戳 ≤ 快照时点的 run 按快照上界判定计入，聚合结果与聚合启动时刻的磁盘状态一致；创建时间晚于快照时点的 run 不计入本轮（非本轮数据，下一轮自省自然纳入）。
- 口径可复现：聚合执行耗时长（大 runs 目录）不使窗口边界漂移，统计口径确定。

## 溯源

- 2026-09-18 evo-add-self-review-window-snapshot — 窗口上界由聚合中实时取 now 改为启动时固定快照（治「摘要总 run 数 1 而磁盘实存 2」的并行漏计）
