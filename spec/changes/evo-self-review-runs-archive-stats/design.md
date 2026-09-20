# design: self-review-runs-archive-stats

## D1 并集统计

- 位置：core/self_review.py collect_runs_stats（约 271 行起）。
- 实现：files = 当前目录 glob("*.jsonl") + archive 目录 glob("*.jsonl")（archive 目录不存在时忽略）。
- 文件集合构造参考既有同构实现 core/dashboard/data/summary.py:404-407（runs_dir.glob + arc.is_dir() 后 extend arc.glob），口径与 Dashboard 侧一致。
- 窗口归属：逐文件 _run_start_ts(run_id) 解析 run_id 内嵌开始时间戳（缺失回退 stat().st_mtime），_in_window 与入口快照 window_end 判定——与现有当前目录逻辑完全一致，仅扩展文件集合。
- 同口径覆盖 collect_failed_run_samples（约 325 行起）：该函数是 §2「失败样本」渲染的独立数据源（core/self_review.py:650-666：stats["failed"] 为真时调用），当前同样只 glob 当前目录、只读路径。若只改 collect_runs_stats，会出现「计数含归档失败 run、样本列表不含」的口径分裂。两函数 MUST 采用同一文件集合与同一窗口判定。

## D2 不变量

- review- 前缀 run 继续排除（自省不审视自身）。注意该前缀为 `review-`，与 spec-review-/code-review- 前缀不同：归档目录现存 review-2026-09-20.jsonl（自省 run 自身的归档副本）MUST 被排除，否则自省会把自身计入窗口统计。归档遍历 MUST 复用同一 startswith("review-") 判定，不得放宽为「排除所有含 review 的 run_id」。
- 同 run_id 在当前目录与归档同存的风口按 run_id 去重（当前目录优先）。该形态出现在归档移动与统计并发的窗口内：core/dashboard/data/runs.py:805-831 的保留周期逐文件移档，遇「归档副本已存在」时删顶层副本；archive_spec_runs（core/agent_runner/run_files.py:149-169）同理会删顶层同源副本。当前快照下两目录无同名 stem（实测 comm 无交集），故为防御性去重而非现存缺陷，但 MUST 实现以免并集引入重复计数。
- 只读：不新增任何写操作；collect_runs_stats 契约与调用方（self_review.py:524 零活动防护、self_review.py:650 摘要渲染）不变。

## Non-Goals

- 不引入 manifest 文件（当前无此文件，遍历 archive 目录即可）。
- 不改变归档时机 / runs.keep。