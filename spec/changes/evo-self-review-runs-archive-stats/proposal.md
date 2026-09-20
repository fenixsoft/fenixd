# self-review-runs-archive-stats

## Why

**每日自省 run 统计只统计 .fenix/runs/ 当前目录、不读归档，终态 run 一旦归档即从窗口统计消失——窗口内完成的所有 run 在自省摘要里不可见，浪费归因与 run 统计失真。**

2026-09-21 复核：归档目录 50 个产物、其中非 review- 且落在近 24h 窗口内 20 个（.fenix/runs/archive/；runs.keep=50；fenixd.log 2026-09-19T10:17:09Z「runs 保留: 终态 run 移入归档 …」，该日志在 .fenix/logs/fenixd.log 命中 702 次），而每日自省摘要「总 run 数: 1、成功 0、失败 0」（.fenix/runs/archive/review-2026-09-20.jsonl）——core/self_review.py:271 collect_runs_stats 仅 glob .fenix/runs/*.jsonl 当前目录（core/self_review.py:299），窗口内完成的 run 因已归档而不计入，只有「跨窗口仍在飞」的 run 被计为 running。

> 说明（口径边界）：runs 统计不含成本字段（counts 键仅 total/succeeded/failed/instant_hang/timeout/dropped/running），本 SPEC 使**计数与状态分类**与归档实际一致，成本归因仍由 .fenix/cost/ 独立类目负责、不在本 SPEC 范围。另：evo-transient-storm-alert-context 的 run 产物早于归档目录现存最旧条目（2026-09-19 11:00），已按 runs.keep=50 清理，本 SPEC 不使其回溯可见——归档可见性缺口以「窗口内非 review- 归档 run 20 个 vs 摘要总 run 数 1」为证。

本 SPEC 将统计源改为「当前目录 + 归档目录」并集，按 run_id 内嵌开始时间戳统一判定窗口归属（复用 _run_start_ts / _in_window / _classify_run 既有纯函数），使窗口成功/失败/秒挂/超时计数与状态分类与归档实际一致。同一并集口径同步覆盖「失败样本可追溯」通道 collect_failed_run_samples，避免计数含归档、样本仍只看当前目录的口径分裂。

> 注：todo 建议所称「runs-archive-manifest」清单当前不存在（归档目录无 manifest 文件），实现直接遍历 .fenix/runs/archive/*.jsonl 即可，无需先建 manifest。