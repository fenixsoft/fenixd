## Why

自省 run 聚合 collect_runs_stats 的窗口上界取实时 `datetime.now()`（core/self_review.py:110-111 `_in_window`），与 agent_runner 派发并发执行——聚合时点恰在 run 文件创建前时漏计刚派发的 run。scheduling-showcase 实证：自省摘要『总 run 数: 1 / 在跑: 1』，而 .fenix/runs/ 磁盘实存 2 个盲跑 implementer run（impl-c-sched-set/clear-1789101576，review 自省 run 按前缀排除），漏计直接低估浪费规模、误导闭环判定。任何并行派发环境下该竞态都会周期性低估自省数据。

## What Changes

- `collect_runs_stats` 窗口上界改为聚合启动时点的固定快照（函数入口取一次 `now` 并贯穿 `_in_window` 判定），聚合执行期间不再使用实时时钟。
- 对同一窗口内的 `collect_log_errors` 等聚合一致化（若共用 _in_window）。
- 无 dashboard UI、无新配置键；自省统计输出格式不变。

## Capabilities

### New Capabilities
- `self-review-window-snapshot`: 自省聚合窗口上界固定快照，消除与派发并行的计数竞态

### Modified Capabilities
无 requirement 级修改：聚合口径语义（[window_start, now] 闭区含义不变，仅 now 改为快照值）。

## Impact

- **core/self_review.py**：`_in_window` / `collect_runs_stats` / `collect_log_errors` 上界快照化。
- **tests/**：聚合与派发并行竞态的确定性单测（构造快照边界 run）。