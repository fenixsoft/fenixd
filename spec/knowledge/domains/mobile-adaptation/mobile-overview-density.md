<!-- knowledge: capability=mobile-overview-density rev=1 sources=spec/archive/2026-09-13-fix-mobile-overview-tiles -->

# 概览页移动端密度

概览页（overview）统计卡与项目清单在移动端的信息密度契约：去重复标题、收紧内边距、数字注释完整换行、搜索框全宽可用。

## 规则

- 统计卡单标题：<768px 视口下，IntroduceRow 四张统计卡（SPEC 总数 / 任务进度 / Token 消耗 / 活跃 Agent 运行）只保留卡头标题一行，卡内自绘灰眉题不渲染（Tooltip 信息图标保留）；≥768px 保持卡头黑粗标题 + 灰眉题双标题布局。
- 内边距：移动端统计卡 body 内边距为 12px 16px；桌面保持 16px 24px。
- 数字注释不截断：移动端统计卡的数字与注释行（Token 卡「平均每 SPEC X」、活跃 Agent 卡数字 + 类型图例）允许换行展示，注释文本完整可读，不因 nowrap / overflow:hidden 出现省略截断或挤压。
- 项目清单卡头两行：移动端卡头第一行为标题，第二行为搜索框与状态过滤组；搜索框撑满卡体可用宽度、可正常聚焦输入，过滤组不与标题挤压同一行。≥768px 保持单行卡头（标题 + 160px 搜索框 + 过滤组）。

## 溯源

- [2026-09-13 fix-mobile-overview-tiles](spec/archive/2026-09-13-fix-mobile-overview-tiles/) — 建立统计卡移动端单标题/收紧内边距/数字换行与项目清单卡头两行、搜索框全宽的密度契约
