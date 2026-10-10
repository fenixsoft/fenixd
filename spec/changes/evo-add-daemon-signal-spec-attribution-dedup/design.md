## Context

派发链路两条：存储信号摄取循环（core/admin_monitor.py:2906-2909，mergeback_wip_overlap 走此路）与巡检链路 _handle_signal（core/admin_monitor.py:4295-4298，daemon_errors 走此路）。在飞互斥 D2b 现有三处（:2834、:4269、:4523）均为 if spec and self._has_active_admin_run_for_spec(spec)——daemon 级信号 spec 为 None 时守卫短路失效；daemon run 的 spec 占位为 global（_spec_has_active_admin_run 按名互查，:886），与 spec 级信号永不互见。单信号到单 run 绑定：_invoke_administrator（:5712，signal_rec 单条），终态回写 mark_signal_handled（:5951-5979）。既有聚合：_make_daemon_error_signal_merged（:3964，alert-noise-governance 3.2）只合并 daemon_errors 同轮多指纹；归档 fix-admin-cross-type-duplicate-dispatch（2026-10-07）只统一到 spec 单键。再武装范式：:2826-2830 注释所述「记录未消费、在飞 run 结束后自然重评」已成型。机制解释：阻塞类 ERROR 由 2 分钟级自动重试反复落日志，10 分钟 3 次即触发 daemon_errors 同指纹升级，与 spec 级信号唤起几乎必然重叠——两例实证：admin-pack2-live-stream-player-1791610649 与 admin-global-1791610649 同秒双派（fenixd.log:13642/13643，run_metrics :13687/:13692）；admin-pack2-live-stream-player-1791602498 与 admin-global-1791602544 间隔 46 秒双开（run_metrics :13419/:13462）。

## Goals / Non-Goals

- Goals：同源阻塞事件的 daemon 级信号不再与 spec 级信号双派；跳过后有确定的自然重评路径，不丢处置。
- Non-Goals：不做单 run 回写多 disposition 的重结构；不加派发延迟窗口；不改指纹升级阈值与 _make_daemon_error_signal_merged 语义。

## Decisions

- D1 选「派发前按归属互查跳过」而非 todo 原建议的「同 spec 且 5 分钟窗口合并派发」：双信号 spec 字段不同（pack2-live-stream-player 对 null/global），同 spec 判据对实际形态不成立，须先做 evidence spec 归属提取；而延迟窗口会拖慢 critical 信号且需要派发缓冲/重放，改动面大。互查跳过零延迟、disposition 回写路径零改动。
- D2 归属提取以 evidence 文本为主：分支名 fenix/<spec>-<时间戳> 正则 + spec 名直接匹配，双线索任一命中即归属；提取不到即兜底现状。不做跨 run 结果关联等更重的归因。
- D3 跳过时信号不 mark handled，附注记「被在飞 run 覆盖、待重评」，复用 :2826-2830 所述在飞 run 结束后自然重评；重评时若 pre-probe 判定诉求已满足（_preprobe_signal_satisfied 语义），按既有语义闭环。

## Risks / Trade-offs

- 归属提取误判（把无关 spec 名提进来）会导致漏派：以分支名/spec 名强模式限定 + 仅当该 spec 确有在飞 run 才跳过，误判窗口窄；且信号保持未消费、仍会重评，最坏退化为先后各派一次（等于现状），无额外损失。
- 在飞 run 失败收口时被跳过信号重评再派：等于现状行为，可接受。