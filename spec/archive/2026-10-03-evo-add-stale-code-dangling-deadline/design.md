## Context

- 陈旧检测：fenixd.py:191-228 以 core/**/*.py + fenixd.py 的 mtime 指纹比对启动基线（_code_baseline_ns）；主循环 30s 节拍经 _update_stale_code_state（fenixd.py:1011-1103）维护 self._code_stale，假→真边沿写 stale_code 告警且写入即 mark_handled（fenixd.py:1095-1096，2026-09-13 降噪决策）。
- 空闲自愈：_maybe_stale_selfheal_tick（fenixd.py:1535-1724，主循环 1s 粒度调用）要求 _is_idle（fenixd.py:1105-1160，五维空闲判据、连续空闲 ≥ idle_confirm_seconds 缺省 120s）持续满足才 touch .fenix/restart_request；阻断分支只清零计时。全链路无悬空时长计量。
- 规划性排水（evo-fix-planned-restart-drain-effectiveness 已落地）：restart_request 由 bin/fenixd_supervisor.py:444 起轮询消费，SIGTERM 后 daemon shutdown 以 planned_restart=True 进入排水（fenixd.py:3832-3908）：broadcast_restart_checkpoint → agent_runner.drain_wait（agents.run_drain_max_seconds 缺省 60s）→ 超窗 _preserve_interrupted_runs sidecar（.fenix/interrupted_runs.json）+ _preserve_implementing_specs，重启后 boot recovery 断点续做；supervisor SIGKILL 窗口 = shutdown_drain_seconds + 120s 余量（bin/fenixd_supervisor.py:214-224）。
- 告警基建：AdminStore（core/admin_store.py：append/mark_handled/latest_signal/unhandled_for）；60 分钟去重常量 STALE_ALERT_DEDUP_MINUTES（fenixd.py:105-114）；「需人工知悉」warning 模式参照 stale_selfheal_cooldown（fenixd.py:1382-1422，写入即留在待处理视图）。注意 fenixd.py:1387-1388 注释已明示 stale_code 类型因写入即 handled 不适合复用——升级告警必须用新 signal_type。
- 配置：.fenix/config.yaml:304-305 stale_code_selfheal.enabled=true；读取入口 ConfigLoader.get_stale_code_selfheal_config（core/config.py:1396），缺省常量在 core/config.py:1371-1380。

## Goals / Non-Goals

- Goals：悬空可计量、超时可升级（忙时也能换上已合回的修复）、升级对人工可见。
- Non-Goals：不改变空闲自愈的零中断优先路径；不动 supervisor 协议与排水实现；不做基线漂移的 git 级比对（沿用 mtime 指纹）；不含落地前的人工重启运维步骤。

## Risks / Trade-offs

- 忙时强推重启会中断在飞 run：由 planned_restart 排水兜底（60s 宽限 + checkpoint + sidecar 断点续做），代价是有界重跑；相对无限期悬空的复发敞口（单日实测 2.1 小时合回停摆 + 2 批弃现场）是划算交换。
- 重启风暴：超时分支复用既有 cooldown（cooldown_window 1800s / cooldown_threshold 3）与 self-triggered 闸门（fenixd.py:1645-1686）；4 小时时限远大于冷却窗口。
- mtime 指纹误报（touch 无内容变更）：与现状同风险面，本 SPEC 不放大——重启加载同内容代码无害。
- 时钟：_code_stale_since 用 UTC，与 restart_history.jsonl 现有时间戳同源。

## Migration Plan

1. 落地代码 + 单测合回。
2. 运维一次性清积压：低负载窗口 touch .fenix/restart_request（本 SPEC 外的人工步骤），加载当前全部悬空修复。
3. 观察首个悬空超时周期：确认升级告警出现且未自动 handled、重启后 _code_stale 归零、在飞 run 经排水保全或宽限收尾。

## Open Questions

- max_dangling_seconds 缺省 4 小时是否合宜：白天 code-fix 高频节律下意味着最多损失一个批次的排水重跑，可依观察调整。