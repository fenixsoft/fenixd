## Why

add-spec-subtitle-and-row-click 落地后，详情页中文标题经 PageTitleBar 既有 subtitle 槽渲染——该槽组件形态是**标题行内右侧**（英文标题同行、灰色小字），与用户需求「英文标题**下方**」不符（2026-11-06 用户裁决：修成下方堆叠）。需要 PageTitleBar 支持副标题下方堆叠形态，两详情页（v1 detail / v2 specDetail）生效。

## What Changes

- **组件堆叠形态**（新增）：`PageTitleBar` 新增副标题下方堆叠声明（标题与副标题上下两行；声明页生效，其余既有 subtitle 消费面渲染形态不变）。
- **两详情页切换声明**（修改）：v1 detail（中文标题）与 v2 specDetail（中文标题 · branch 组合）改用堆叠形态，branch 副标题随之移到下方，两页形态一致。
- **偏移常数回校**（同步面）：堆叠使标题栏实际高度增加，两详情页及其页内 sticky 元素对标题栏高度的依赖常数（若命中 56/60、126/130 同族字面量）盘点并回校，pageTitleBar / pageChrome / embedMount 既有守卫测试同步。

**非目标**：列表名称列副标题（已是下方堆叠，不动）；其余 subtitle 消费面（若有）不改堆叠声明。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `unified-page-title-bar`（活跃能力）：新增「副标题下方堆叠形态」需求（声明页两行堆叠；未声明页行内形态不变）。

## Impact

- **代码面**：纯前端——`components/PageTitleBar.tsx` + 两详情页 + 既有前端守卫测试；无后端改动。
- **风险面**：标题栏高度变化触及偏移常数族同步面（5 常量 4 测试纪律）——以两详情页实际渲染为准盘点回校，守卫测试兜底防回潮。
