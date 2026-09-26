# spec-review-rejection-schema 能力增量（add-pipeline-throughput-governance）

> spec-review 打回理由结构化契约：打回（reviewing→drafted）时结果 JSON 必写 `rejection_class` 枚举字段，缺字段按 unknown 兼容，用于统计与降噪。

## ADDED Requirements

### Requirement: rejection_class 字段契约

spec-review 结果为打回（触发 reviewing→drafted）时，结果 JSON MUST 包含 `rejection_class` 字段，枚举固化为：`format`（草稿结构/契约段/键名等可机械修复问题）、`substantive`（方案、场景覆盖、正确性等实质问题）；判定标准 MUST 经评审 prompt 注入段下发（`format` 与 `substantive` 的边界定义逐条列出）。通过（reviewing→ready）的结果 MUST NOT 要求该字段（可省略或为 null）。读侧与统计口径对缺字段/非法值 MUST 按 `unknown` 兼容处理，存量结果文件零迁移、MUST NOT 因缺该字段被判非法。

#### Scenario: 格式打回带分类

- **WHEN** 评审因草稿缺契约段打回某 SPEC
- **THEN** 结果 JSON 含 `rejection_class: "format"`，打回理由正文不变（人类可读说明照旧）

#### Scenario: 实质打回带分类

- **WHEN** 评审因场景未覆盖核心功能点打回某 SPEC
- **THEN** 结果 JSON 含 `rejection_class: "substantive"`

#### Scenario: 存量结果缺字段兼容

- **WHEN** 读侧解析一份无 `rejection_class` 字段的历史打回结果
- **THEN** 按 `unknown` 处理，解析不失败、不告警升级，统计中归入 unknown 桶

### Requirement: 分类统计可查询

读侧数据层 MUST 提供按 `rejection_class` 分桶的打回统计（spec 级或全局级均可，形式不限：summary 字段或查询函数），`format` 桶占比用于评估「机械可预防打回」规模。统计 MUST fail-open（无数据返回空），本期不要求前端组件。

#### Scenario: 统计分桶正确

- **WHEN** 近期 3 次打回分别为 format、substantive、unknown（缺字段）
- **THEN** 统计输出三桶计数 {format: 1, substantive: 1, unknown: 1}，无数据 spec 返回空值不抛异常
