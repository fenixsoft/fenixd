# admin-dispatch-dedup Specification

## Purpose

daemon 级无 spec 信号（daemon_errors 同指纹升级等）与 spec 级信号源自同一阻塞事件时，框架当前 1:1 双派 administrator run 重复诊断（实测两例：412.8 秒+449.9 秒，及 3117 秒与 3831 秒量级双开）。本能力让 daemon 级信号在派发前按证据归属到 spec 并与在飞 admin run 互查，命中即跳过、待在飞 run 结束后自然重评，消除重复处置且不丢处置机会。

## Requirements

### Requirement: daemon 级信号 evidence 携带 ERROR 原文摘录

daemon_errors 升级信号（单指纹与同轮多指纹合并形态）组装时，MUST 把最近一次同指纹 ERROR 原文摘录（含组件名、截断限长）附入 evidence，作为归属提取的基底；信号 description 的「指纹 <fp[:8]>」前缀子串与 `_fp`/status_hash 判据 MUST 保持不变（跨重启已知指纹对账依赖）。

#### Scenario: 升级信号 evidence 含原文摘录

- **WHEN** 同指纹 ERROR 达升级阈值、构造 daemon_errors 升级信号
- **THEN** 信号 evidence 含该指纹最近一次 ERROR 原文摘录，且 description 仍以「指纹 <fp[:8]>」开头

### Requirement: daemon 级信号派发前 spec 归属提取

daemon 级信号（spec 字段为空）进入派发判定前，MUST 尝试从信号 evidence 中的 ERROR 原文摘录提取 spec 归属；evidence 无 spec 线索（或无摘录的存量形态）时 MUST 返回空归属且不改变后续派发行为。

#### Scenario: ERROR 原文含 spec 线索

- **WHEN** daemon_errors 升级信号的 evidence ERROR 原文含 spec 名或实现分支名（如 fenix/pack2-live-stream-player-1791608995 形态）
- **THEN** 派发判定能取得该信号的 spec 归属 pack2-live-stream-player

#### Scenario: 无 spec 线索兜底

- **WHEN** daemon 级信号 evidence 无任何 spec 名或分支名线索
- **THEN** 归属为空，派发流程与现状完全一致

### Requirement: spec 归属命中在飞 run 时跳过派发

daemon 级信号提取到 spec 归属后，若该 spec 已有在飞 admin run，MUST 跳过本次派发：信号保持未消费（不 mark handled），附「被在飞 run 覆盖、待重评」注记，在飞 run 终态后按既有再武装范式自然重评。跳过语义 MUST 限定于具检测循环重发生命周期的 daemon 级信号类型（当前唯一 spec=None 形态为 daemon_errors，其指纹过窗再升级即重发）；无重发生命周期的 None-spec 信号类型不得套用本跳过。

#### Scenario: 同源阻塞事件双信号

- **WHEN** spec 级 mergeback_wip_overlap 信号已派发 admin run 且在飞，同一阻塞事件的 daemon_errors 升级信号随后到达派发判定
- **THEN** daemon 级信号被跳过、不派发新 run，在飞 run 收口后该信号获得重评机会

#### Scenario: 在飞 run 收口后重评

- **WHEN** 被跳过的信号仍 open 且覆盖它的 admin run 已达终态
- **THEN** 该信号按既有重评机制重新进入派发判定；若诉求已被在飞 run 满足，按既有 pre-probe 语义闭环而非重复派发

### Requirement: 无在飞 run 时行为不变

无 spec 归属或归属 spec 无在飞 admin run 时，daemon 级信号 MUST 按现状 1:1 派发；_make_daemon_error_signal_merged 同轮多指纹合并与既有 D2b spec 键在飞互斥语义 MUST 不回归。

#### Scenario: 独立 daemon 异常

- **WHEN** daemon_errors 信号归属不到任何有在飞 admin run 的 spec
- **THEN** 照常派发 administrator run，处置时效不受本能力影响