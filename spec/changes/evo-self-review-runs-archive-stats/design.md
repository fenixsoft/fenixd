# design: self-review-runs-archive-stats

## D1 并集统计

- 位置：core/self_review.py collect_runs_stats（约 271 行起）。
- 实现：files = 当前目录 glob("*.jsonl") + archive 目录 glob("*.jsonl")（archive 目录不存在时忽略）。
- 窗口归属：逐文件 _run_start_ts(run_id) 解析 run_id 内嵌开始时间戳（缺失回退 stat().st_mtime），_in_window 与入口快照 window_end 判定——与现有当前目录逻辑完全一致，仅扩展文件集合。

## D2 不变量

- review- 前缀 run 继续排除（自省不审视自身）。
- 同 run_id 在当前目录与归档同存的风口按 run_id 去重（当前目录优先）。
- 只读：不新增任何写操作；collect_runs_stats 契约与调用方（self_review.py:524/650）不变。

## Non-Goals

- 不引入 manifest 文件（当前无此文件，遍历 archive 目录即可）。
- 不改变归档时机 / runs.keep。