## Context

守卫现状：core/code_fix.py _night_quiet_state（:2853 起，:2866-2869 只判当前时刻）+ checkpoint 守卫块（:3215、:3276-3290），窗缺省 04:15-04:45（:2312 NIGHT_QUIET_WINDOW_DEFAULT），config 键 admin.code_review_fix.night_quiet_window（:2836），窗末时刻基建 _local_window_end_epoch（:2354）。admin 唤起：core/admin_monitor.py _invoke_administrator（:5229，:5273-5282 仅查在队与信号死法冷却）；瞬断冻结态源在 core/agent_runner/provider_circuit.py（:967、:1128）；pm_engine 队列已有冻结闸（core/pm_engine/dispatch/queue.py:695）但 admin 车道不经该队列。

## Goals / Non-Goals

- Goals：夜间断窗期不新派注定被杀的 run；同链近批时长已被 run_metrics 记录（turns/时长），估计值零额外观测成本。
- Non-Goals：不做在飞 run 的窗前主动回收（由既有 salvage/超时监督兜底）；不改 admin 信号的升级与冷却语义。

## Decisions

- D1 预计跨窗用「近批实测均时长」而非静态批大小折算：run_metrics 已有数据、对慢批次自适应；估计保守取近 N 批均值。
- D2 admin 避放闸门放在 _invoke_administrator 单点而非入队侧：admin 车道不经 pm_engine 队列，唤起点是唯一收口；跳过而非丢弃，下一轮盘点自然重试。
- D3 窗常量复用：admin 避让直接引用 code_fix 的窗解析（或抽公共小模块），不引入第二份窗配置。

## Risks / Trade-offs

- 预计跨窗会推迟部分本可赶在窗前完成的短批：可接受——错过的是 04:10-04:15 极窄区间，收益是避免整批被杀重跑。
- admin 跳过在断窗拉长时会推迟处置：与「派了必死」相比净收益为正，且升级通道 fail-closed 兜底仍在。