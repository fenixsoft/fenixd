## ADDED Requirements

### Requirement: pending/unknown 门的兜底归因文案

六道门合成（`parse_quality_gates` 产出 items）完成后，对 status 为 pending 或 unknown 且
`detail` 为空串的门项，MUST 填充固定归因文案后再返回：

- pending 且 detail 为空 → 固定文案「该门未了结（run 在飞或自查结果未落盘）」；
- unknown 且 detail 为空 → 固定文案「门禁记录缺失或损坏」。

约束：

- 已有非空 detail 的门项（含 failed 归因原文、running「进行中」、skipped 原因、
  passed 计数摘要、implementing 分支的「实现 run 在飞，收尾门禁未了结」、
  full-suite 终态豁免文案等）MUST 原样保留，兜底文案不覆盖；
- 文案在**读侧合成层**填充（后端），前端经既有 detail 透传链渲染，前端零改动；
- done 计数口径不变：兜底文案不改变任何门的 status。

#### Scenario: pending 空详情获得兜底文案

- **WHEN** 某门合成结果为 pending 且 detail 为空串（如 run 自查键未写、ocr 车道产物不可见）
- **THEN** 该门 detail 为「该门未了结（run 在飞或自查结果未落盘）」，status 不变

#### Scenario: unknown 空详情获得兜底文案

- **WHEN** 某门合成结果为 unknown 且 detail 为空串（如 quality-gates.json 整体缺失或损坏）
- **THEN** 该门 detail 为「门禁记录缺失或损坏」，status 不变

#### Scenario: 已有归因文案零覆盖

- **WHEN** 某门已有非空 detail（如 failed 的打回归因原文、implementing 的
  「实现 run 在飞，收尾门禁未了结」、full-suite 终态豁免文案）
- **THEN** detail 原样保留，兜底逻辑不生效

#### Scenario: UI 无解释未勾选项消除

- **WHEN** 详情页渲染六道门勾选列表
- **THEN** 任何未勾选项（pending/unknown）都携带非空解释文案，不再出现零说明的未过项
