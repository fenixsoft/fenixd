# v2-commercial-ui Spec

## ADDED Requirements

### Requirement: v2 SPEC 表格名称列中文副标题

项目详情（/v2/projects/:name）SPEC 表格名称列 SHALL 在 SPEC 英文名主行下方渲染中文标题副标题行（数据源同条目 `title` 字段）：副标题用 v2 台账次级文字 token（`V2_TEXT_TERTIARY` 或同级）且字号小于主行、单行省略，随主行对齐；`title` 为 null/空时不渲染副标题行（保持既有单行形态）。副标题不改变既有名称单元格交互：点击进 v2 SPEC 详情、悬停 `title` 属性（英文名溢出提示）等行为不变；表格列集、排序、窄屏卡片形态不受影响。

#### Scenario: v2 表格有标题条目渲染副标题

- **WHEN** v2 SPEC 表格某行条目 `title` 为「知识收件箱回填管线」
- **THEN** 该行名称单元格英文名下方渲染次级中文副标题（V2 次级文字色、小字号、单行省略）

#### Scenario: v2 表格无标题条目保持单行

- **WHEN** v2 SPEC 表格某行条目 `title` 为 null
- **THEN** 该行名称单元格仅渲染英文名，布局与改动前一致

#### Scenario: v2 名称交互不变

- **WHEN** 用户点击名称链接进入 v2 SPEC 详情
- **THEN** 跳转行为与改动前一致，副标题文本不承载独立点击目标
