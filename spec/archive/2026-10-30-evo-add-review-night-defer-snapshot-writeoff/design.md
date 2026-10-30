# 设计：review-night-defer-snapshot-writeoff

## D1 窗模型多窗化的兼容策略

`_parse_night_quiet_window`（core/code_fix.py:3096）保持签名不变（内部改调复数版取首窗），新增 `_parse_night_quiet_windows(raw) -> list[tuple[start_min, end_min, text]]`：

- 解析按 `,`/`;` 分段，每段走既有 `_parse_night_quiet_hhmm` 单段校验；任一段非法或出现 `end<=start` 逆序 → 整体返回 None（宁缺毋错，不部分生效）。
- 消费点改造：code-fix 守卫 `_night_quiet_window` 命中判定改「任一窗 start<=cur<end」；`_local_window_end_epoch` 改取命中窗自身的 end（多窗同时命中取最晚 end）；窗次武装告警的窗次标识含命中窗文本；`_night_dispatch_block_reasons`（core/admin_monitor.py:5421）同口径读列表。
- 风险：窗次幂等键从窗文本派生，配置变更当日会出现新旧两窗次标识——可接受（告警按窗次幂等，不拦截投递）。

## D2 周期审查跨窗顺延

挂点在 `_run_code_review_checkpoint` 既有守卫链尾部、单飞判定之后、manifest 收集之前（core/admin_monitor.py，约 :1600 前后），原因：manifest 收集与 save_code_review_state 均有副作用，顺延判定必须先于二者。

- 时长样本：读 `.fenix/runs/archive/code-review-*.jsonl` 尾部 run_metrics 行的 `duration_s`，取最近 3 轮成功轮均值（对齐 `NIGHT_QUIET_DURATION_SAMPLE_LIMIT = 3`，core/code_fix.py:3074）；读失败/无样本回退「仅判派发时刻落窗」。
- 命中即返回 `{"triggered": False, "reason": "night_quiet_window_deferred"}`：不写 `save_code_review_state`（否则同日防重使当日永不跑）、复位单飞标志（对齐空 manifest 分支既有复位口径，:1624 附近）。
- 与 provider 瞬断冻结不复用：冻结态已有全局冻结闸，本判定只管窗相交。
- 边界：多窗与预计区间相交取最晚窗末为「下一可派发时刻」，仅用于日志文案；实际派发交由巡检自然到达。

## D3 scheduled 全仓核销资格放宽

maintenance_runs.py:1721 条件改为 `run_ok and (review_kind == "manual_full" or (review_kind == "scheduled" and window_start is None))`：

- 复用守卫：redispatch_of 分支与普通分支的 `_writeoff_coverage_guard` 判定原样生效——scheduled 全仓轮被 agent 静默少审时（09-19 事故形态）同样被锁，不白洗。
- observed 非空门（:1738 注释的空集核销修复）原样生效。
- 不放行 manual_window / 窗口档 scheduled：窗口审查只增不核销是模块头声明的不变量（core/code_review.py:14），保持。
- `resolve_snapshot` 本体不动（core/code_review.py:875）。

## D4 pending-writeoff 锚

- 文件：`.fenix/code-review/writeoff-pending.json`，内容 `{run_id, inserted, updated, at}`；辅助函数 `write_pending_writeoff / read_pending_writeoff / clear_pending_writeoff` 落 core/code_review.py（与 items_path 同目录同锁风格，flock 原子写）。
- 写入点：error 收场抢救 inserted 或 updated > 0 时（maintenance_runs.py:1856 前后），覆盖写（新事故顶旧锚，只留最近一次待核销现场）。
- 清除点：任一收尾执行了 `resolve_snapshot` 且 resolved>0，或覆盖完整成功收尾（核销解锁分支走完）。
- 展示：admin_monitor 完成日志（:1676 / :1917 两处落账文案）在读到锚时追加「部分覆盖待核销」标注；不加告警、不进 dashboard 新页（观测走日志）。

## Risks

- 多窗化使非法配置面变宽（多段中一段坏即整体无窗）：WARNING 一次 + 单测覆盖混合非法样例，风险可接受。
- scheduled 全仓核销首启时台账 90+ 条陈旧 open 会被一次性批量置 resolved：这正是核销语义（未再观测即消失），且 observed 非空门防白洗；design 阶段确认无消费方依赖「resolved 只能来自 manual_full」。
- 顺延判定读归档 jsonl 尾行有 IO 成本：仅命中 run_at 后首轮巡检执行一次，非热路径。