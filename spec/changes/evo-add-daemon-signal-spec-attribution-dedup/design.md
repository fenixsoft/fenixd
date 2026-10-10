## Context

派发链路两条：存储信号摄取循环（core/admin_monitor.py:2906-2909，mergeback_wip_overlap 走此路）与巡检链路 _handle_signal（core/admin_monitor.py:4295-4298，daemon_errors 走此路）。在飞互斥 D2b 现有三处（:2834、:4269、:4523）均为 if spec and self._has_active_admin_run_for_spec(spec)——daemon 级信号 spec 为 None 时守卫短路失效；daemon run 的 spec 占位为 global（_spec_has_active_admin_run 按名互查，:886），与 spec 级信号永不互见。单信号到单 run 绑定：_invoke_administrator（:5712，signal_rec 单条），终态回写 mark_signal_handled（:5951-5979）。既有聚合：_make_daemon_error_signal_merged（:3964，alert-noise-governance 3.2）只合并 daemon_errors 同轮多指纹；归档 fix-admin-cross-type-duplicate-dispatch（2026-10-07）只统一到 spec 单键。再武装范式：:2826-2830 注释所述「记录未消费、在飞 run 结束后自然重评」已成型。机制解释：阻塞类 ERROR 由 2 分钟级自动重试反复落日志，10 分钟 3 次即触发 daemon_errors 同指纹升级，与 spec 级信号唤起几乎必然重叠——两例实证：admin-pack2-live-stream-player-1791610649 与 admin-global-1791610649 同秒双派（fenixd.log:13642/13643，run_metrics :13687/:13692）；admin-pack2-live-stream-player-1791602498 与 admin-global-1791602544 间隔 46 秒双开（run_metrics :13419/:13462）。

## Goals / Non-Goals

- Goals：同源阻塞事件的 daemon 级信号不再与 spec 级信号双派；跳过后有确定的自然重评路径，不丢处置。
- Non-Goals：不做单 run 回写多 disposition 的重结构；不加派发延迟窗口；不改指纹升级阈值与 _make_daemon_error_signal_merged 语义。

## Decisions

- D1 选「派发前按归属互查跳过」而非 todo 原建议的「同 spec 且 5 分钟窗口合并派发」：双信号 spec 字段不同（pack2-live-stream-player 对 null/global），同 spec 判据对实际形态不成立，须先做 evidence spec 归属提取；而延迟窗口会拖慢 critical 信号且需要派发缓冲/重放，改动面大。互查跳过零延迟、disposition 回写路径零改动。
- D2 归属提取以 evidence 文本为主：**evidence 基底须先补齐**——评审实测 daemon_errors 信号 evidence（单指纹 :3948-3962、合并 :3982-4008）仅含「指纹 <fp[:8]> 复现 N 次（最近一次 <时间戳>）；升级条件：…」摘要串，不含 ERROR 原文、分支名或 spec 名；故第一步在两处组装点把最近一次同指纹 ERROR 原文摘录（含组件名，截断限长）附入 evidence，第二步从该摘录做「分支名 fenix/<spec>-<时间戳> 正则 + spec 名直接匹配」双线索归属，任一命中即归属；提取不到即兜底现状。description 的「指纹 <fp[:8]>」前缀保持不变（跨重启已知指纹对账依赖）。不做跨 run 结果关联等更重的归因。
- D3 跳过时信号不 mark handled，附注记「被在飞 run 覆盖、待重评」。自然重评的车道语义：daemon_errors 走 _handle_signal 车道（:4269 守卫），该车道被跳过时按既有 `_persist_skipped_disposition` 范式补写 result="skipped" 处置（:4275-4284——DISPOSITION 不参与 unhandled_for 节流、不阻断「在飞处置完成后的自然重评」），重评由检测循环的重发生命周期驱动（阻塞 ERROR 持续则同指纹过冷却窗后再升级重发；诉求已被在飞 run 满足则错误止息、不再升级，等效 pre-probe 闭环）。:2826-2830 所述「记录未消费、在飞 run 结束后由摄取循环重评」是存储信号摄取车道（mergeback_wip_overlap 等 store 记录）的对应形态，两车道语义同构；实现时按信号实际所在车道挂接，勿把 daemon_errors 跳过错接到摄取循环记录路径。

## Risks / Trade-offs

- 归属提取误判（把无关 spec 名提进来）会导致漏派：以分支名/spec 名强模式限定 + 仅当该 spec 确有在飞 run 才跳过，误判窗口窄；且信号保持未消费、仍会重评，最坏退化为先后各派一次（等于现状），无额外损失。
- 归属提取漏检（ERROR 原文未点名 spec/分支）则双派照旧：提取产出的上限取决于错误文案是否点名 spec——评审时点两例动机现场的日志已轮转不可复核（fenixd.log 已滚转，:13642 附近与 run_metrics 引用无法回读），无法证明原文必含线索；本能力对命中案例消除双派、对未命中案例零损失，验收不得以「双派归零」为门槛（Non-Goal 化）。
- 跳过波及面约束：全库 _make_signal 构造点核对（11 处），spec=None 的 daemon 级信号现状仅 daemon_errors 一族，其重发生命周期（指纹过窗再升级）已确证；跳过语义 MUST 限定于「具检测循环重发生命周期」的 daemon 级信号类型——未来新增无重发生命周期的 None-spec 信号类型不得套用本跳过（否则会被静默吞掉且无重评），届时须先补该类型的重评通路。
- 在飞 run 失败收口时被跳过信号重评再派：等于现状行为，可接受。