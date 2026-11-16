## Why

add-spec-subtitle-and-row-click 落地后，详情页中文标题一度经 PageTitleBar 既有 subtitle 槽渲染——该槽组件形态是标题行内右侧（英文标题同行、灰色小字），与用户需求「英文标题下方」不符（2026-11-06 用户裁决：修成下方堆叠）。同日晚间实现已按用户多轮指令落地（5e085bb0c 下方行更正 + 6d7ead201 两列结构）：中文标题撤出 subtitle 槽、作为块级第二行收进 richTitle 富标题内部（组件未新增堆叠声明，subtitle 槽行内形态原样保留给概览等消费面），两详情页形态一致，守卫测试已钉死。本 SPEC 就该已落地形态成文留痕并契约化（fast-track，同 add-spec-list-mobile-style 先例）。

## What Changes

- **详情页富标题内部下方行**（已落地）：v1 detail（中文标题）与 v2 specDetail（中文标题 · branch 组合，单源 combineSpecSubtitle）的中文标题作为块级第二行收进 richTitle 富标题内部（12px tertiary、单行省略、贴排 lineHeight 14px、`width: 0 / minWidth: 100%` 定宽不推开右簇）；两页 PageTitleBar 声明零 subtitle 槽，branch 副标题随之在下方行组合呈现。
- **两列结构与移动端只显标题**（已落地）：richTitle 左列（英文名+中文下方行）、右簇（模式/状态 Tag/胶囊 + 快速切换下拉/状态转移）分列，外层 alignItems center 使右簇随标题块整体取中；移动端 `!isMobile`/`!mobile` gate 只显英文标题（右簇与中文下方行均不渲染）。
- **偏移常数盘点**（已完成）：两详情页实测未命中标题栏高度依赖的 56/60、126/130 同族字面量，既有常数未动；pageTitleBar / pageChrome / embedMount 既有守卫测试已同步。

**非目标**：PageTitleBar 组件不新增堆叠声明（subtitle 槽行内形态与既有消费面不变）；列表名称列副标题（已是下方堆叠，不动）。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `unified-page-title-bar`（活跃能力）：新增「SPEC 详情页中文标题富标题内部下方行」需求（两详情页生效；subtitle 槽行内形态消费面不变）。

## Impact

- **代码面**：纯前端——已落地于两详情页 + PageTitleBar 富标题适配 + 守卫测试（specTitleSubtitle / pageTitleBar / embedMount）；无后端改动；本 SPEC 收尾确认与 dist rebuild 锚点刷新。
- **风险面**：堆叠使标题块高度增加，两详情页偏移常数盘点未命中（无 56/60、126/130 族依赖），页签/内容区无遮挡错位；守卫测试防回潮。
