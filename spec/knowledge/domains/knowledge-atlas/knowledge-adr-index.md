# ADR 决策索引

<!-- knowledge: capability=knowledge-adr-index rev=1
     sources=spec/archive/2026-10-05-add-knowledge-atlas -->

真相源的架构决策层：从归档 SPEC 的 design.md 抽取跨 SPEC 影响架构走向的裁定，形成编号、可溯源、不可变的决策条目。

## 规则

- 收录判据（高门槛、宁缺勿滥）：仅收约束后续 SPEC 实现空间的裁定与跨模块机制选型（如「车道隔离必须走 spawn 点注入」「写读必须同层」「蒸馏 run 主树直跑不做 merge-back」级别）；单 SPEC 内部实现取舍（页面布局、函数命名、校验细节、文案措辞）不收录。一个归档 SPEC 可以产出零条 ADR。
- 条目格式：`adr/ADR-NNN-<标题>.md`，头部含 `date` 与 `status: accepted | superseded`，正文三段式 `## Context`（问题背景）/ `## Decision`（裁定）/ `## Consequences`（后果与代价）。编号 NNN 三位递增，接续目录既有最大号。
- 不可变性：ADR 一经落盘即为不可变文档，后续蒸馏不得改写已 accepted 条目的正文；校验器以 tracked ADR 正文与 HEAD diff 对账，任何改动即违规。
- Supersede 只标不改：新 ADR 推翻旧裁定时，对旧条目只做两处标记——头部 `status:` 翻为 superseded、追加 `Superseded by: ADR-NNN(<新标题>)` 行，三段正文逐字保持原样。「是否构成取代」的语义判断归蒸馏提示词裁定（给正反例、允许零产出），supersede 的机械部分（链接指向存在条目、状态翻转、正文未变）归校验器对账。
- 索引：`adr/index.md` 表格列出全部 ADR（编号链接、状态、一句话摘要），superseded 条目保留在列供溯源；新条目落盘时同步登记，读者可据索引总览全部决策及状态。

## 溯源

- 2026-10-05 add-knowledge-atlas（spec/archive/2026-10-05-add-knowledge-atlas/） — 新增本能力页：抽取判据、三段式与不可变性、supersede 只标不改、索引登记
