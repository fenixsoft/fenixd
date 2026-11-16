# Design: add-titlebar-subtitle-stacked

## Context

PageTitleBar 现有 subtitle 槽为行内形态（`BackArrow + TitleNode + SubtitleNode` 同一 baseline flex 行，`columnGap: 10`，两壳位同构排布）；add-spec-subtitle-and-row-click 曾把两详情页中文标题经该槽渲染为「标题同行右侧」灰字，与用户「英文标题下方」诉求不符（2026-11-06 用户裁决修成下方堆叠）。同日晚间实现已按用户多轮指令落地：中文标题撤出 subtitle 槽、作为块级第二行收进 richTitle 富标题内部（5e085bb0c 下方行更正 + 6d7ead201 两列结构与移动端只显标题），subtitle 槽行内形态与既有消费面（概览等页）不变。

## Goals

1. 两详情页中文标题呈英文标题下方堆叠形态、branch 组合语义保留、两页一致（已达成）。
2. subtitle 槽未声明面零变化；形态由守卫测试钉死防回潮。

## Decisions

- **D1 富标题内部下方行（而非组件堆叠声明）**：中文标题不新增 `PageTitleBar` subtitleBelow 之类声明，而是作为块级第二行收进 richTitle 富标题内部（12px tertiary、单行省略、贴排 `lineHeight: 14px`；`width: 0 / minWidth: 100%` 定宽使中文行不参与左列 max-content 定宽、右簇不被中文行宽度推开）——详情中文标题要确定性换行位置（不随宽度漂移），且富节点路线让模式/状态 Tag、快速切换下拉随标题块两列结构整体垂直居中；subtitle 槽行尾跟随形态留给概览等页（组件不全局翻转，v2 branch 先例与其余消费面不被动迁）。
- **D2 两壳位同构**：richTitle 经 title 槽位落行壳位与顶栏槽，控件对富节点透明不拆解重组（spec-detail-quick-switch 契约延续），wrap 语义在行壳位内继续成立（mobile-detail-header-density 载体迁移）；embed 档同规则。
- **D3 偏移常数以实测为准**：堆叠使标题块增高，但两详情页实测未命中标题栏高度依赖常数（56/60、126/130 同族字面量零命中），既有常数不动（避免全族误改——titlebar 同步面纪律「5 常量 4 测试」以实际同步面为准）；pageTitleBar / pageChrome / embedMount 守卫测试已同步钉死。
- **D4 移动端只显标题**：`!isMobile` / `!mobile` 页级 gate 下中文下方行不渲染（同 subtitle 槽既有规则）；2026-11-06 用户指令「移动端设备样式中只显标题」进一步把右簇（模式/状态 Tag/胶囊 + 快速切换下拉/状态转移）一并隐藏——移动端仅英文标题。

## Risks

- **富标题换行交互**：标题行保持 `flexWrap: wrap`（mobile-detail-header-density 契约），窄视口外层 wrap 右簇下坠（同旧 wrap 形态）；390px 视口回归由既有移动端测试兜底。
- **实现与文档偏差回潮**：守卫测试（specTitleSubtitle 零 subtitle 槽 + 富节点下方行断言、pageTitleBar、embedMount）已钉死实际形态，防实现回退 subtitle 槽路线。
