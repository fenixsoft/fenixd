# 审查 run 停滞看门狗

<!-- knowledge: capability=review-run-stall-watchdog rev=1
     sources=spec/archive/2026-10-03-decouple-codefix-review-lanes -->

周期审查 run 的停滞自动收走机制：双判据判定「无产出」，达阈值自动取消并走既有急救落账，把僵死 run 占用的车道与锁在有界时间内释放，不再依赖人工取消 + 重启。

## 规则

- 判定对象是 admin monitor 周期节拍中的在飞审查 run；检查随 admin monitor 巡检环执行，不另起线程、不依赖前端轮询。
- 停滞判据为双判据合取，两者同时无进展才计停滞：① 进度产物最新 mtime（主产物 + 全部分片，分片发现经 `shard_paths` 唯一入口）；② run 子进程进程树 CPU 时间。任一判据有进展即整体重置计时。
- 阈值 `admin.review_stall_minutes`（分钟），缺省 30；缺失/非法/非正整数（含 bool）一律回退 30，巡检路径不因配置脏值中断。
- fail-open 面：CPU 判据不可解析（进程句柄缺失/已退出/读取异常）时不触发——宁可漏杀不可误杀，且无句柄时取消原语也无从终止；产物暂缺或 stat 失败沿用上一轮记录的 mtime（产物短暂不可读不视为进展、也不误触发重置清零，无上一轮记录才兜底 0.0）；run 不在飞即短路并清理判定状态。
- 达阈值动作按序：`cancel_run(run_id, by="review_stall_watchdog")`（既有 run 粒度取消原语，属主轮询环完成 terminate→grace→kill→cancelled）→ run 收尾走既有急救落账路径（error 收场抢救已完整落盘的产物，不新造落账路径）→ AdminStore 告警留痕。
- 告警为 ESCALATION（severity=major，`signal_type=review_stall_watchdog`），去重键 `review-stall-watchdog-<run_id>`，单 run 至多一条；evidence 携带双判据冻结值（mtime、CPU 秒、停滞分钟数）与取消结果；取消调用失败仍落告警留痕。
- 急救落账条目照常落 `open`，但看门狗取消收场 MUST NOT 激活 code-fix 修复链——链激活仅由「审查成功收尾且落账 inserted>0」驱动。
- 误杀处置：判为误杀时在「代码审查」分面手动重审一次即可，产物无损失（急救已入账，对照 error 收场抢救日志的 inserted/updated 读数复核）。

## 关键行为

- 取消经由 agent_runner 的取消原语由属主轮询环收口，看门狗自身不直接杀进程；run 到达终态后判定状态即清理，不重复取消。
- 与零进度停滞告警（[code-review-progress-visibility](code-review-progress-visibility.md)）互补：那一条让零产物被看见（仅告警），这一条让僵死 run 被收走（自动取消）；两者阈值键（`stall_alert_minutes` / `review_stall_minutes`）与去重键相互独立。

## 溯源

- 2026-10-03 decouple-codefix-review-lanes（spec/archive/2026-10-03-decouple-codefix-review-lanes） — 新建本页：双判据停滞看门狗（产物 mtime × 进程树 CPU、任一有进展即重置、CPU 不可用 fail-open）、阈值 admin.review_stall_minutes 缺省 30、自动取消 + 既有急救落账 + 单 run 去重告警、取消收场不激活修复链。
