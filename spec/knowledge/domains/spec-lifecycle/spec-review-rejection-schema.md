# 评审打回分类契约（rejection_class）
<!-- knowledge: capability=spec-review-rejection-schema rev=1
     sources=spec/archive/2026-09-27-add-pipeline-throughput-governance -->

spec-review 打回结果的结构化分类字段：区分「机械可修复」与「实质问题」两类打回，供统计与降噪。

## 规则

- spec-review 结果为打回（触发 reviewing 回退重做）时，结果 JSON 必须包含 `rejection_class` 字段，枚举固化为：
  - `format`：草稿结构、契约段、键名等可机械修复问题；
  - `substantive`：方案、场景覆盖、正确性等实质问题。
- 判定标准经评审 prompt 注入段下发，`format` 与 `substantive` 的边界定义逐条列出；打回理由正文（人类可读说明）照旧不变。
- 结果为通过（reviewing → ready）时不要求该字段（可省略或为 null）。
- 读侧与统计口径对缺字段/非法值按 `unknown` 兼容（`normalize_rejection_class`）：解析不失败、不告警升级、统计归入 unknown 桶；存量结果文件零迁移，不得因缺该字段被判非法。
- 分类随 STATE 持久化（spec entry 的 `_review_rejection_class`）作为 spec 级可追溯冗余，统计查询函数 `rejection_class_stats` 直接扫描结果文件按 `rejection_class` 分桶。
- 读侧数据层提供按 `rejection_class` 分桶的打回统计（spec 级或全局级均可）；`format` 桶占比用于评估「机械可预防打回」规模；统计 fail-open（无数据返回空，不抛异常）；本期不要求前端组件。

## 溯源

- 2026-09-27 2026-09-27-add-pipeline-throughput-governance — 新增打回分类契约：rejection_class 枚举与 prompt 注入判定标准、缺字段 unknown 兼容与存量零迁移、分桶统计与 fail-open
