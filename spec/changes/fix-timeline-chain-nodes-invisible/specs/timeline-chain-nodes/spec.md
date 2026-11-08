# 时间轴处置链节点前端渲染

## ADDED Requirements

### Requirement: chain 节点卡片渲染

SPEC 运行时间轴对 `kind === "chain"` 节点渲染紧凑链事件卡片：标题行含时间、`chain_kind` 中文标签 Tag、`signal_type` 副标签；正文一行展示 `summary`；卡片形态复用 Bento 磁贴（`cardBox`：12px 圆角、发丝边、软阴影、纯白底）。圆点着色与标签着色同源。

- 六种 `chain_kind` 映射：`chain-dispatch`→链派发(blue)、`chain-handoff`→转单 Arbiter(gold)、`chain-closed`→链闭环(green)、`chain-escalated`→链终点上升(orange)、`chain-recurrence`→复现(orange)、`chain-choice-failed`→choice 执行失败(red)。
- 分支置于既有兜底守卫之前；兜底守卫语义不变（真正未知 kind 仍降灰点）。
- state 节点的 `item.chain` 状态序列字段消费零改动（命名防混淆：链节点判定仅以 `item.kind === "chain"` 为准）。

#### Scenario: 各链事件渲染为可读卡片

- **WHEN** 时间轴数据含 `chain-handoff` 节点（summary 为 Admin 转单理由摘要、signal_type=inconclusive_loop）
- **THEN** 渲染出链事件卡片：标题行含「转单 Arbiter」gold Tag 与 signal_type 副标签，正文含 summary 文本
- **AND** 六种已知 `chain_kind` 各自渲染对应中文标签与着色（链闭环绿、链派发蓝、上升/复现橙、choice 失败红）

#### Scenario: 裸灰点形态退役

- **WHEN** 时间轴数据含已知 `chain_kind` 节点
- **THEN** 该节点不再渲染为无卡片体的裸灰点（DOM 中该 listitem 含卡片内容结构）

### Requirement: 未知链形态安全兜底

未知 `chain_kind`（台账未来新增而前端未跟）渲染中性「处置链」灰标签卡片，不报错、不崩时间轴渲染。

#### Scenario: 未知 chain_kind 中性兜底

- **WHEN** 节点 `kind="chain"` 且 `chain_kind` 不在映射表（如 "chain-future-kind"）
- **THEN** 渲染中性「处置链」灰 Tag 卡片（summary 照常展示），时间轴整体渲染不抛错

### Requirement: 无链事件零回归

时间轴数据不含 chain 节点时，既有四类节点（state/admin/verify/run）渲染与折叠行为零变化。

#### Scenario: 无链事件 spec 时间轴不变

- **WHEN** 时间轴数据仅含 state/admin/verify/run 节点（无任何 `kind="chain"` 条目）
- **THEN** 渲染输出与改动前一致（四类分支与兜底守卫路径零回归）
