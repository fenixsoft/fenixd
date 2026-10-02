<!-- knowledge: capability=run-superseded-terminal rev=1 sources=spec/archive/2026-09-16-fix-retry-orphan-active-runs -->

# 被取代 run 的终态标记

原地重试弃置的产物文件补写 superseded 终态，配读侧陈旧兜底，维持产物「末行恒为终态」不变量、消除 running 尸体。

## 现行规则

- 写侧补写：runner 原地退避重试的两个通道（provider 瞬断、artifact-gate 失败）在写 `transient_retry` 事件、且后续将以新 `sub_run_id` 重开产物文件（`transient_retries` 递增换新）或退出重试子循环时，必须先向当前产物文件补写一条 `type: "superseded"` 终态事件（含 spec、provider、timestamp 字段），再进入退避 sleep；重试 attempt 写入新文件 `<attempt_run_id>-r<N+1>.jsonl`，旧文件不再被追加。
- daemon 在退避窗口内死亡时，停机/启动清扫向该文件追加的 `interrupted` 位于 superseded 之后，「末行恒为终态」不变量仍成立。
- 读侧识别：`classify_run` 对末行 superseded 判终态（`_RUN_TERMINAL_STATUS_MAP` 映射 superseded → superseded），不落入 running 兜底。
- 读侧 mtime 陈旧兜底：产物末行非终态（running/empty）且文件 mtime 距今超过 `_RUN_STALE_SECONDS`（模块常量 1800 秒）时状态改判 `stale`；阈值内的非终态文件保持 `running`（真在退避/执行）。`stale` 为读侧专属状态枚举（不对应任何事件类型），不写入任何产物文件；`project_summary.active_runs` 只认 running/empty，不计入 stale。

## 溯源

- 2026-09-16 fix-retry-orphan-active-runs（spec/archive/2026-09-16-fix-retry-orphan-active-runs） — 确立 superseded 终态补写时点、读侧终态识别与 1800 秒 stale 兜底，全量消化存量 transient_retry 尸体文件
