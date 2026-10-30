# 管理员派发去重（daemon 级信号归属互查）

<!-- knowledge: capability=admin-dispatch-dedup rev=1
     sources=spec/archive/2026-10-30-evo-add-daemon-signal-spec-attribution-dedup -->

Administrator 派发的同源去重防线：daemon 级无 spec 信号在派发前按证据归属到 spec，与该 spec 的在飞 admin run 互查，命中即让路待重评，消除同一阻塞事件的重复诊断 run。

## 规则

- daemon_errors 升级信号（单指纹与同轮多指纹合并两种形态）组装时，evidence 携带最近一次同指纹 ERROR 原文摘录（含组件名、截断限长），作为 spec 归属提取的基底；信号 description 恒以「指纹 <fp[:8]>」开头，`_fp`/status_hash 判据不变——跨重启已知指纹对账依赖该稳定文案。
- daemon 级信号（spec 字段为空）进入派发判定前先做 spec 归属提取：对 evidence 中的 ERROR 原文摘录按双线索匹配——实现分支名（fenix/<spec>-<时间戳> 形态）正则与 spec 名直接匹配，任一命中即归属该 spec；evidence 无 spec 线索时归属为空，后续派发行为与无此判定完全一致。
- 归属 spec 已有在飞 admin run 时跳过本次派发：不唤起新 run，信号保持未消费（不 mark handled），补写 result="skipped" 处置并附「被在飞 run 覆盖、待重评」注记。
- 跳过不等于消费：覆盖 run 达终态后，仍 open 的被跳过信号按既有重评机制重新进入派发判定；若诉求已被在飞 run 满足，错误止息不再升级，按既有 pre-probe 语义闭环而非重复派发。重评由信号自身的重发生命周期驱动（daemon_errors 同指纹过冷却窗再升级即重发）。
- 跳过语义限定于具检测循环重发生命周期的 daemon 级信号类型（当前唯一 spec=None 形态为 daemon_errors）；新增无重发生命周期的 None-spec 信号类型不得套用本跳过——须先补该类型的重评通路，否则信号会被静默吞掉。
- 兜底不变：提取不到归属、或归属 spec 无在飞 admin run 时，daemon 级信号照常 1:1 派发 administrator run，处置时效不受影响；同轮多指纹合并（一条信号一次 run）与既有 spec 键在飞互斥（D2b）语义保持不变。
- 归属误判的窗口被双条件收窄（强模式限定 + 仅在归属 spec 确有在飞 run 才跳过），且信号未消费仍会重评，最坏退化为先后各派一次；提取产出的上限取决于错误文案是否点名 spec，验收不以「双派归零」为门槛。

## 关键行为

- admin 信号派发判定有两条车道：存储信号摄取循环（mergeback_wip_overlap 等 store 记录走此路）与巡检链路 `_handle_signal`（daemon_errors 走此路），两车道跳过语义同构——记录未消费、在飞 run 结束后由所在车道自然重评；daemon_errors 的 skipped 处置经 `_persist_skipped_disposition` 既有形态补写，不落摄取循环记录路径。

## 溯源

- 2026-10-30 evo-add-daemon-signal-spec-attribution-dedup（spec/archive/2026-10-30-evo-add-daemon-signal-spec-attribution-dedup） — 新增本能力页：daemon_errors 信号 evidence 补 ERROR 原文摘录、派发前双线索 spec 归属提取、归属命中在飞 run 即跳过派发（不消费、待重评），兜底与合并/互斥既有语义保持
