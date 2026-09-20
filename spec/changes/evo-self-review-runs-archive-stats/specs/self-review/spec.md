# self-review 能力规格：runs-archive-stats

## 概述

每日自省窗口 run 统计覆盖归档记录，统计口径与归档实际一致。

## 现状与缺口

- collect_runs_stats 只 glob .fenix/runs/*.jsonl（当前目录）；
- 终态 run 即时移入归档（runs.keep=50）→ 窗口内完成 run 不计入统计，摘要数字失真。

## 规格

- 统计源 = 当前目录 *.jsonl ∪ 归档目录 *.jsonl（归档目录缺失时退化为仅当前目录）；
- 窗口归属按 run_id 内嵌开始时间戳判定（缺失回退文件 mtime），统一复用既有辅助函数；
- 同一并集口径覆盖「失败样本可追溯」通道 collect_failed_run_samples（计数与样本 MUST 同源，不得计数含归档而样本只看当前目录）；
- 保持排除 `review-` 前缀（自省 run 自身；区别于 spec-review-/code-review- 前缀）、只读遍历、不触发写操作；输出 counts 键不变（total/succeeded/failed/instant_hang/timeout/dropped/running）。

## 边界

- 不改变归档时机与 runs.keep 阈值（归档目录条目受 runs.keep=50 上限清理，早于窗口且已被清理的 run 本 SPEC 不使其回溯可见）；
- 不改变 _classify_run 的分类口径；
- 不引入成本字段（counts 键不含成本；成本归因由 .fenix/cost/ 独立类目承担）。