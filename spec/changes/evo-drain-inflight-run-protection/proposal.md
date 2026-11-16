# Proposal: drain-inflight-run-protection

## Why

悬空超时强制重启（stale_code_dangling_timeout）只在 daemon 忙时触发——边沿由主树 core/ 变更产生、在飞 run 持续清零空闲计时，故必然撞上在飞 run。已四次成灾：2026-10-31 drain 50s 杀 2 run（含 code-review-1793462564）、11-04 窗杀 planner/impl 两 run、11-05 窗 6 run 约 114 分钟作废、2026-11-10 17:47:29Z 告警 591f9f54784a 触发的强制重启在 50 秒排水后 SIGTERM 杀掉跑了 106 分钟（duration_s=6373.17、694 轮）的全仓审查 run code-review-1794326531（exit 143），剩余 156/353 文件覆盖延迟 22h14m 才由 writeoff 锚续审接管。三个结构性缺口回源核实（行号经 spec-review 实测校正）：(1) 计划内排水窗实际仅 50 秒——agents.run_drain_max_seconds 缺省 60（core/config.py:2484 回退分支）被 planned=True 分支 min(值, supervisor SIGKILL 等待−10s) 夹紧（core/config.py:2488-2493），本部署 admin.shutdown_drain_seconds=0（.fenix/config.yaml:112）→ SIGKILL 等待回退 60s → cap=50s（fenixd.log:6048「drain window 50.0s」实证），单提一处会被静默夹回；(2) 排水前 checkpoint 广播（core/agent_runner/runner.py:10326 broadcast_restart_checkpoint，由 fenixd.py:7247 调用）落了旗标但全仓无读取方，code-review 车道不响应，drain-preserve（fenixd.py:7042-7072）按 worktree→spec 保全集操作、code-review 车道无 worktree 结构性不在保全集；(3) code-review 车道 writeoff 锚驱动的剃余续审（core/admin_monitor.py:2323-2400）消费点嵌在每日周期函数内、被 last_run_date 同日防重闸（:2227-2229）挡住——被杀当天只能等次日，22 小时空窗由此而来。

## What Changes

- 排水窗成对扩容：agents.run_drain_max_seconds 缺省提到 300；按既有夹紧口径（core/config.py:2424-2432）联动调整 admin.shutdown_drain_seconds 缺省与回退路径，使缺省部署的有效排水窗≥300；并在既有配置一致性门（core/config.py:1375-1388）补「有效排水窗被夹短」显式告警，杜绝静默夹回。
- code-review 车道响应重启 checkpoint 旗标：code-review run 为单次 _run_agent 派发、agent 自切批直写分片（无 Python 层波次循环），经 prompt 注入批边界自检实现——每批分片直写后读广播旗标，置位时完成当前批收尾（分片已直写落盘+终态抢救文件写毕+剩余清单写 writeoff 锚）即退出，不再开启新批，把「等不到收尾」从结构性变成单批粒度。
- writeoff 锚即时消费：把锚检查从每日周期函数提为独立周期扫描（复用 AdminMonitor 既有 5 分钟 tick），命中未核销锚即触发剃余续审；绕过 last_run_date 同日闸的条件限定为「writeoff 锚在册」（该闸语义是当日已完成一轮，锚在场恰证明当日未完成）；保留夜窗顺延与单飞闸。
- 可观测性顺带修：writeoff_resume 续审 run 的档案注记 reason 硬编码 429 ratelimit（core/agent_runner/maintenance_runs.py:2798）改为真实原因 writeoff_resume，与续审检索对账键一致（core/admin_monitor.py:2260）。

## Impact

- Affected specs: daemon-lifecycle（新能力页）
- Affected code:
  - core/config.py（排水窗缺省与一致性告警）
  - core/agent_runner/runner.py（checkpoint 旗标单源/读取辅助）
  - core/agent_runner/maintenance_runs.py（波次边界旗标响应+reason 修正）
  - core/admin_monitor.py（writeoff 锚周期扫描）
  - tests/test_drain_inflight_run_protection.py（新增单测）