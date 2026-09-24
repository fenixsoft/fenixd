## Why

2026-09-24 17:52-20:39 合回的 7 个系统性修复（marker 声明窗口、选批 WIP 预检、规划性重启排水、worktree 撞名换名重试、stale 告警窗口去重、WIP 周期合回消费者、迟到结果终态丢弃）因 daemon（2026-09-24 16:45:05 启动）此后未重启而持续悬空，悬空期已实际复发一次同形态故障（20:23 worktree 分支撞名 ERROR，.fenix/logs/fenixd.log:21518-21526）。现有空闲自愈以「连续空闲 ≥ idle_confirm_seconds」为硬前置（fenixd.py:1535-1724 + 1105-1160），当前负载形态几乎不产生连续空闲窗口；stale_code 告警又是假→真边沿一次性触发且写入即 mark_handled（fenixd.py:1095-1096），悬空时长没有计量、没有按时间升级的路径，代码基线漂移可以被无限期静默。

## What Changes

- stale_code_selfheal 配置族新增 max_dangling_seconds（缺省 14400 秒 = 4 小时，0 = 关闭升级）。
- daemon 在代码基线进入陈旧态时记录悬空起点；悬空超过时限后不再等待全空闲，直接复用既有 restart_request → supervisor SIGTERM → planned_restart 在飞排水（宽限收尾 / checkpoint 保全 / 断点续做）通道执行安全重启。
- 悬空超时触发时写一条需人工知悉的升级告警（新 signal_type=stale_code_dangling_timeout，不写入即 handled），复用 60 分钟写入去重。

## Impact

- 影响：fenixd.py（陈旧态悬空计量 + 自愈 tick 超时分支 + 升级告警）、core/config.py（新配置键）、tests/test_stale_code_selfheal.py（单测）。
- 不改变既有空闲自愈路径（空闲时仍走零中断自愈）；超时分支仍受既有 cooldown / self-triggered 闸门约束，不引入重启风暴。
- 不改动 supervisor 协议与排水实现（bin/fenixd_supervisor.py 与 shutdown 排水原样复用）。
- 落地前的一次性积压清空（人工在低负载窗口 touch .fenix/restart_request）属运维步骤，不在本 SPEC 交付物内。