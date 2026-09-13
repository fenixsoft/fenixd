## Context

概览页统计卡（IntroduceRow）复刻 ant-design-pro analysis 页布局：卡头 ant-card-head-title 黑粗标题 + 卡内自绘灰眉题双标题设计在 PC 上是刻意的视觉复刻，但移动端构成纯冗余。数字行的 `whiteSpace:'nowrap'`（L171 活跃 Agent 行另含 `overflow:'hidden'`）与 body padding（`styles.body` 内联 `16px 24px`，IntroduceRow.tsx L14）均为内联样式，CSS 覆盖需 `!important`——仓库已有同手法先例（global.less alert-banner `max-width:100% !important`，L176）。项目清单搜索框 `width: 160` 为内联样式（ProjectCards.tsx L152）。

移动端 CSS 作用域约定由 spec A `fix-mobile-breakpoint-hook-tables` 确立：`#root :is(.screen-xs, .screen-sm)` = <768px。本 spec 全部规则按该约定追加在 global.less 尾部。

## Goals / Non-Goals

**Goals:**
- 移动端统计卡：单标题、padding 12px 16px、数字注释行换行不截断
- 移动端项目清单：卡头两行、搜索框全宽可输入
- PC 端双标题 / 24px / nowrap 单行 / 160px 搜索框逐像素不变

**Non-Goals:**
- 不改统计卡的图表（Area/NormalizedBar）与数据口径
- 不改桌面端信息架构（不删除 PC 灰眉题）
- 不动网格列布局（`minmax(170px,1fr)` 实测 390 下 2 列无溢出，符合「实测良好不动」清单）

## Decisions

1. **TSX 只加 4 处 className，其余全走 CSS**：桌面零风险的最低侵入路径；className 命名 `overview-intro-row` / `overview-tile-eyebrow` / `overview-tile-numrow` / `overview-project-card`。
2. **移动端隐藏灰眉题而非隐藏卡头标题**：Tooltip 信息图标在卡头 extra（L41–47），保卡头保 tooltip 信息；移动端视觉层级靠字重/颜色而非重复字号。
3. **`!important` 压内联样式**：CARD_BODY 与 nowrap 均为内联，规则限定在移动断点作用域内，有 alert-banner 先例，可接受。
4. **卡头换行复用 activities 卡既有范式**（`.ant-card-head-wrapper { flex-wrap: wrap }`，global.less L157 同款）。

## Risks / Trade-offs

- [`!important` 特异性压制失效] → 内联样式只能靠 `!important` 覆盖；实施后以 devtools 实测 padding/white-space 生效为准。
- [三 spec 并行触碰 global.less] → 本 spec 仅尾部追加，与 spec A（改既有段落）不同区域，git 可自动合并。

## Migration Plan

单 commit 落地，`max build` 后 :8787 实时生效，无需重启 daemon。回滚 = revert。

## Open Questions

（无）
