# unified-page-title-bar Spec

## ADDED Requirements

### Requirement: SPEC 详情页中文标题富标题内部下方行

v1 SPEC 详情与 v2 SPEC 详情两页 SHALL 将中文标题（v2 为「中文标题 · branch」单源组合）渲染为标题富节点（richTitle）内部的**块级第二行**（12px tertiary 既有次级样式、单行省略、贴排、左对齐与英文标题首字对齐），不再经 PageTitleBar subtitle 槽渲染（两页声明零 subtitle 槽）；title 缺失不渲染，branch 组合语义（branch 空只显中文标题、title 空维持 branch 单独显示、双空不渲染）保持。richTitle 呈两列结构（左列 = 英文名 + 中文下方行；右簇 = 模式/状态标记与页内操作），右簇随标题块整体垂直居中。移动端 MUST 只显英文标题（中文下方行与右簇均不渲染）。既有 subtitle 槽消费面 MUST 保持行内右侧形态不变（组件不全局翻转）。

堆叠使标题块增高后，命中标题栏高度依赖的页内偏移常数（56/60、126/130 同族字面量）SHALL 按实际渲染盘点回校；实测两详情页零命中，既有常数未动。既有守卫测试（pageTitleBar / pageChrome / embedMount）同步钉死。

#### Scenario: 详情页中文标题堆叠在下方

- **WHEN** 打开 v1 或 v2 SPEC 详情页（中文标题非空、非移动端）
- **THEN** 中文标题渲染在英文标题下方独立一行，左对齐标题首字，不出现在标题行右侧，也不经 subtitle 槽（页面声明零 subtitle 槽）

#### Scenario: branch 组合语义保持

- **WHEN** v2 详情页 detail 响应 title/branch 取四分支组合（双非空 / 仅 title / 仅 branch / 双空）
- **THEN** 下方行经单源 combineSpecSubtitle 组合呈现（「中文标题 · branch」/ 中文标题 / branch / 不渲染）

#### Scenario: subtitle 槽消费面形态不变

- **WHEN** 打开任何既有 subtitle 槽消费面（如概览页）
- **THEN** 副标题仍为标题行内右侧形态，与改动前一致

#### Scenario: 移动端只显标题

- **WHEN** 窄屏视口打开 v1 或 v2 SPEC 详情页
- **THEN** 仅渲染英文标题（中文下方行与模式/状态右簇均不渲染）

#### Scenario: 偏移常数盘点

- **WHEN** 详情页标题块因下方行增高
- **THEN** 两详情页未命中标题栏高度依赖偏移常数（56/60、126/130 族零命中），页签/内容区无遮挡错位，pageTitleBar / pageChrome / embedMount 守卫测试全过
