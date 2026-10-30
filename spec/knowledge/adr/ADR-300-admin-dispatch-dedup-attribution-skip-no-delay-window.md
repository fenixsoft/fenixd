# ADR-300：admin 派发去重走派发前归属互查跳过，禁派发延迟窗口与合并回写重结构

date: 2026-10-30
status: accepted

## Context

同一阻塞事件会同时产生 spec 级信号（如 mergeback_wip_overlap）与 daemon 级同指纹升级信号（daemon_errors，spec 字段为空），派发器按信号 1:1 各派一个 administrator run，双 run 重复同一诊断链（实测同秒双派与 46 秒间隔双开，各 300–450 秒量级，其中一个零增量产出）。在飞互斥守卫以 spec 名为键，daemon 级信号 spec 为空时守卫短路失效。候选解法中「同 spec 且时间窗合并派发」对实际形态不成立（双信号 spec 字段不同，一为具体 spec、一为空/global），且延迟窗口会拖慢 critical 信号处置、引入派发缓冲与重放机制。

## Decision

- daemon 级 None-spec 信号与 spec 级信号的同源双派问题，解法收口为「派发前 evidence 归属提取 + 在飞互查跳过」：daemon_errors 信号组装点把最近一次同指纹 ERROR 原文摘录（含组件名、截断限长）附入 evidence，派发判定前从摘录按双线索（实现分支名 fenix/<spec>-<时间戳> 正则、spec 名直接匹配）提取归属，归属 spec 确有在飞 admin run 即跳过派发；跳过不消费信号（不 mark handled）、附待重评注记，由信号自身重发生命周期驱动自然重评。
- 禁建派发延迟缓冲窗口：admin 信号派发保持零延迟，不以聚合换时效；不做「合并派发单个 run、回写多信号 disposition」的重结构——单信号↔单 run 绑定与 mark_signal_handled 回写通道保持不变。
- 跳过语义只授权给具检测循环重发生命周期的 None-spec 信号类型（当前唯一形态 daemon_errors，同指纹过冷却窗再升级即重发）；新增无重发生命周期的 None-spec 信号类型不得套用本跳过，须先补该类型的重评通路，否则信号会被静默吞掉且无重评。

## Consequences

- 误判窗口被双条件收窄（强模式限定 + 仅在归属 spec 确有在飞 run 才跳过），且信号未消费仍会重评，最坏退化为先后各派一次，等于无此能力；归属漏检（错误文案不点名 spec/分支）则双派照旧——本裁定对命中案例消除双派、对未命中案例零损失，相关验收不得以「双派归零」为门槛。
- 信号 description 的「指纹 <fp[:8]>」稳定文案继续承载跨重启已知指纹对账，evidence 扩展不得改写它；同轮多指纹合并（一条信号一次 run）与既有 spec 键在飞互斥语义不受影响。
- 后续 admin 派发聚合类诉求若需要延迟窗口或一 run 多 disposition 回写，须显式 supersede 本 ADR。
