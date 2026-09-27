## ADDED Requirements

### Requirement: ADR 抽取判据（跨 SPEC 架构级决策）

蒸馏 run SHALL 从被归档 SPEC 的 `design.md` `## Decisions` 段中抽取**跨 SPEC 影响架构走向**的决策生成 ADR 条目，写入 `spec/knowledge/adr/ADR-NNN-<标题>.md`（NNN 为三位递增编号）。判据 SHALL 为高门槛、宁缺勿滥：仅当该决策约束了后续 SPEC 的实现空间、或确立了跨模块的机制选型（如「车道隔离必须走 spawn 点注入」「写读必须同层」级别的裁定）时收录；单 SPEC 内部的实现取舍（如某页面的布局选择、某函数的命名）MUST NOT 收录。一个归档 SPEC 可以产出零条 ADR。

#### Scenario: 内部取舍不产生 ADR

- **WHEN** 蒸馏 run 处理一个 design.md 仅含局部实现决策（某 UI 布局、某校验细节）的归档 SPEC
- **THEN** `spec/knowledge/adr/` 不新增任何条目

#### Scenario: 架构级决策被收录

- **WHEN** 蒸馏 run 处理的归档 SPEC 其 Decisions 含跨模块机制选型（如新增一种全局调度机制的设计裁定）
- **THEN** `adr/` 新增一条 ADR，编号接续既有最大 NNN，`adr/index.md` 同步登记

### Requirement: ADR 三段式与不可变性

ADR 条目 SHALL 为三段式：`## Context`（问题背景）、`## Decision`（裁定）、`## Consequences`（后果与代价），头部含状态行（`status: accepted | superseded`）与日期。ADR 一经落盘 SHALL 视为不可变文档：后续蒸馏 MUST NOT 改写已 accepted 的 ADR 正文；档案化的原始决策文本保持原样。

#### Scenario: ADR 正文稳定

- **WHEN** 后续归档的 SPEC 涉及与既有 ADR 相同主题但未推翻它
- **THEN** 既有 ADR 正文保持逐字不变，`adr/index.md` 中其状态仍为 accepted

### Requirement: Supersede 链（取代不改写）

新 ADR 与既有 ADR 构成取代关系时，蒸馏 run SHALL 只做两处标记：旧 ADR 头部状态改为 `status: superseded` 并追加一行 `Superseded by: ADR-NNN(新条目)`；`adr/index.md` 中旧条目状态同步。旧 ADR 的三段正文 SHALL 保持原样不改写。`adr/index.md` SHALL 按编号列出全部 ADR 及状态，superseded 条目保留在列（供溯源）。

#### Scenario: 取代关系只留链接

- **WHEN** 归档 SPEC 的决策推翻了既有 ADR-003 的裁定
- **THEN** 新建 ADR-NNN 承载新裁定，ADR-003 正文三段不变、头部出现 `Superseded by: ADR-NNN`，index 中 ADR-003 标记为 superseded 且仍可点击查看原文

#### Scenario: index 可作 ADR 总览

- **WHEN** 读者打开 `adr/index.md`
- **THEN** 能看到全部 ADR 的编号、标题、状态与一句话摘要，accepted 与 superseded 一目了然
