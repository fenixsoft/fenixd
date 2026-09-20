# self-review-runs-archive-stats

## Why

**每日自省 run 统计只统计 .fenix/runs/ 当前目录、不读归档，终态 run 一旦归档即从窗口统计消失——窗口内完成的所有 run 在自省摘要里不可见，浪费/成本归因失效。**

2026-09-20 实证：窗口内 10+ 个实现/评审 run 完成并归档（.fenix/runs/archive/ 50 个归档文件，runs.keep=50；fenixd.log 2026-09-19T10:17:09Z「runs 保留: 终态 run 移入归档 …」），而每日自省摘要「总 run 数: 1、成功 0、失败 0」——core/self_review.py collect_runs_stats 仅 glob .fenix/runs/*.jsonl 当前目录，窗口内完成的 run 因已归档而不计入，只有「跨窗口仍在飞」的 run 被计为 running。本窗口最大浪费（evo-transient-storm-alert-context 白跑 $8.97 双 run）在框架汇总层面无迹可循。

本 SPEC 将统计源改为「当前目录 + 归档目录」并集，按 run_id 内嵌开始时间戳统一判定窗口归属（复用 _run_start_ts / _in_window / _classify_run 既有纯函数），使窗口成功/失败/秒挂/超时/成本统计与归档实际一致。

> 注：todo 建议所称「runs-archive-manifest」清单当前不存在（归档目录无 manifest 文件），实现直接遍历 .fenix/runs/archive/*.jsonl 即可，无需先建 manifest。