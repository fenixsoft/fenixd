## Why
自省聚合的 run 文件收集面（core/self_review.py _collect_run_files）裸 glob("*.jsonl")，把 dsh 车道每个 run 的伴随事件流 .dsh-events.jsonl 当独立 run 计数：10-30 窗 stale=6 全为伴随流（虚增 35%），10-29 窗 stale=22/22 全为伴随流（信号 100% 失真），真实无终态残留连续两窗不可见。读侧 liveness/run_files/dashboard 三处均已排除该后缀，self_review 是唯一落后方。

## What Changes
1. _collect_run_files 两处 glob 结果统一排除 .dsh-events 后缀（对齐 liveness._is_dsh_events_dump 既有判式）。
2. 契约测试：同 run 主文件+伴随流并存时计 1 次、伴随流不入 stale 桶。

## Impact
- core/self_review.py（一处过滤）
- tests/test_self_review_archive_stats.py（补用例）
- 无误伤面：写侧 dsh_adapter.py:262 命名单源保证合法 run_id 不含该后缀