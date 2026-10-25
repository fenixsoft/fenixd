## Context

守卫现状：core/code_fix.py _night_quiet_state（:2853 起，:2866-2869 只判当前时刻）+ checkpoint 守卫块（:3215、:3276-3290），窗缺省 04:15-04:45（:2312 NIGHT_QUIET_WINDOW_DEFAULT），config 键 admin.code_review_fix.night_quiet_window（:2836），窗末时刻基建 _local_window_end_epoch（:2354）。admin 唤起：core/admin_monitor.py _invoke_administrator（:5229，:5273-5282 仅查在队与信号死法冷却）；瞬断冻结态源在 core/agent_runner/provider_circuit.py（:967、:1128）；pm_engine 队列已有冻结闸（core/pm_engine/dispatch/queue.py:695）但 admin 车道不经该队列。

## Goals / Non-Goals

- Goals：夜间断窗期不新派注定被杀的 run；时长可低成本观测——run_metrics 已记 turns（core/agent_runner/runner.py:6359-6377），时长字段现未记录，写入侧补记一行 duration_s（一次性改动，见 D1/任务 1.2）后估计值零额外观测成本。
- Non-Goals：不做在飞 run 的窗前主动回收（由既有 salvage/超时监督兜底）；不改 admin 信号的升级与冷却语义。

## Decisions

- D1 预计跨窗用「近批实测均时长」而非静态批大小折算，对慢批次自适应；估计保守取近 N 批均值。时长数据源（2026-10-07 评审实测修正）：run_metrics 行现无 duration 字段（core/agent_runner/runner.py:6359-6377 归档行与 :6400 附近日志行同源写入，仅 turns/token/latency_stall 类字段）——实现须在写入侧补记 duration_s（两处同源，任务 1.2）；近批无有效样本（新链冷启动/历史行未记时长）时回退既有「仅判派发时刻落窗」行为（fail-open，MUST NOT 因缺样阻塞投递）。
- D2 admin 避放闸门放在 _invoke_administrator 单点而非入队侧：admin 车道不经 pm_engine 队列，唤起点是唯一收口；跳过而非丢弃，下一轮盘点自然重试。落点与人工通道政策（2026-10-07 评审补约定）：仓库内两条先例方向相反——alert-noise-governance 5.1 禁止把抑制类判定放本体（core/admin_monitor.py:3835-3843，防误伤人工显式触发通道），而 evo-sigterm-source-tracking-cooldown 把 spec 级冷却闸放在本体（:5273-5282 并列位）。本闸选定与信号死法冷却同位（本体并列），且两新闸同样作用于人工显式触发：本闸语义是「保护 run 不进必死窗口」而非「抑制噪音召唤」，断窗/冻结期内人工唤起同样必死；code-fix 侧静默窗对手动触发同样生效已有先例（core/code_fix.py:3210-3212 手动授权仅越过 enabled 总开关）。跳过属非失败路径：MUST NOT 增 retry_count、MUST NOT 落升级告警（沿 fixture 抑制「对被抑制记录不增 retry_count」先例，见 _fixture_invocation_suppressed docstring），仅 INFO 留痕原因。
- D3 窗常量复用：admin 避让直接引用 code_fix 的窗解析（或抽公共小模块），不引入第二份窗配置。

## Risks / Trade-offs

- 预计跨窗会推迟部分本可赶在窗前完成的短批：可接受——错过的是 04:10-04:15 极窄区间，收益是避免整批被杀重跑。
- admin 跳过在断窗拉长时会推迟处置：与「派了必死」相比净收益为正，且升级通道 fail-closed 兜底仍在。