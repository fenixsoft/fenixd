# unified-page-title-bar Spec

## ADDED Requirements

### Requirement: SPEC 详情标题栏中文副标题

两个 SPEC 详情页 SHALL 在标题栏标题（英文名富节点）下方经 subtitle 槽渲染中文标题（数据源 `/api/specs/<spec>` 详情 `title` 字段，null/空时不渲染副标题、保持单行现状，与列表副标题缺失规则一致）：

- v1 详情（projects/detail）：PageTitleBar 增声明 subtitle（现无 subtitle 声明）；数据源经详情响应 `title` 字段（页面已拉取的 specList 查表兜底亦可）。
- v2 详情（v2/specDetail）：subtitle 槽已有 branch 声明，组合渲染为 `中文标题 · branch`（branch 缺失时只显示中文标题，title 缺失时维持现状 branch 单独显示）。

移动端维持既有「subtitle 移动端隐藏」规则（SubtitleNode `!isMobile` 判据，零改动）。

#### Scenario: v1 详情标题栏渲染中文副标题

- **WHEN** 进入某 title 非空的 SPEC 的 v1 详情页
- **THEN** 标题栏英文名富节点（含模式/状态 Tag、快速切换下拉）下方渲染中文标题副标题

#### Scenario: v2 详情副标题组合渲染

- **WHEN** 进入某 title 非空且 branch 非空的 SPEC 的 v2 详情页
- **THEN** 副标题为「中文标题 · branch」；branch 为空时只显示中文标题

#### Scenario: 无 title 容错

- **WHEN** 详情 `title` 为 null（缺字段 SPEC）
- **THEN** 两页均不渲染中文副标题，v2 维持 branch 单独显示，布局与改动前一致

#### Scenario: 移动端隐藏不变

- **WHEN** 窄屏视口打开任一详情页
- **THEN** 副标题不渲染（既有 `!isMobile` 规则，零改动）
