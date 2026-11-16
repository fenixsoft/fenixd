<!-- knowledge: capability=mobile-overview-density rev=2 sources=spec/archive/2026-09-13-fix-mobile-overview-tiles,spec/knowledge/_inbox/done/2026-11-16-overview-narrow-width-wrap-and-ledger-scroll-floor.md -->

# 概览页窄宽度密度

概览页（overview）统计卡与项目清单在移动端及窄宽度桌面下的信息密度契约：去重复标题、收紧内边距、数字注释完整换行、搜索框全宽可用。

## 规则

- 统计卡单标题：<768px 视口下，IntroduceRow 四张统计卡（SPEC 总数 / 任务进度 / Token 消耗 / 活跃 Agent 运行）只保留卡头标题一行，卡内自绘灰眉题不渲染（Tooltip 信息图标保留）；≥768px 保持卡头黑粗标题 + 灰眉题双标题布局。
- 内边距：移动端统计卡 body 内边距为 12px 16px；桌面保持 16px 24px。
- 数字注释不截断（作用域=窄宽度全档：<768px 移动档与窄宽度桌面同规则）：统计卡数字与注释行（Token 卡「平均每 SPEC X」、活跃 Agent 卡数字 + 类型图例）以 `flexWrap: 'wrap'` 为通用承载，注释文本完整可读，不因 nowrap / overflow:hidden 裁剪承载出现省略截断或挤压——裁剪承载已退役，不得回迁。Token 卡数字行 wrap（gap 竖 4 横 8），「平均每 SPEC X」注释 span 自带 nowrap 保证作为整体参与换行、不在词中断开；活跃 Agent 卡图例行 wrap（gap 竖 4 横 6），类型图例 inline-flex span 同开 wrap 兜底类型极多场景。宽视口内容放得下时不触发换行，PC 观感零变化（layout-first 承载手法，非宽度微调）。
- 项目清单卡头两行：移动端卡头第一行为标题，第二行为搜索框与状态过滤组；搜索框撑满卡体可用宽度、可正常聚焦输入，过滤组不与标题挤压同一行。≥768px 保持单行卡头（标题 + 160px 搜索框 + 过滤组）。

## 溯源

- 2026-09-13 fix-mobile-overview-tiles（spec/archive/2026-09-13-fix-mobile-overview-tiles） — 建立统计卡移动端单标题/收紧内边距/数字换行与项目清单卡头两行、搜索框全宽的密度契约
- 2026-11-16 2026-11-16-overview-narrow-width-wrap-and-ledger-scroll-floor（spec/knowledge/_inbox/done/2026-11-16-overview-narrow-width-wrap-and-ledger-scroll-floor.md） — 数字注释不截断规则作用域由 <768px 扩至窄宽度桌面：nowrap/overflow:hidden 裁剪承载退役，flexWrap wrap 为通用承载（Token 卡注释 span nowrap 保整体断行、活跃 Agent 类型图例 inline-flex wrap 兜底、宽视口零影响）
