## ADDED Requirements

### Requirement: 移动端小字链接触控目标扩展
global.less SHALL 定义移动端作用域的 `.touch-expand` 工具类：`display:inline-block; padding:8px; margin:-8px`，使命中区扩展至 ≥32px（≥ WCAG 2.5.8 AA 最低 24×24）且视觉与布局零变化（负 margin 完全抵消 padding）。该类 SHALL 落地于四处实测 <44px 的小字链接：SPEC 列表卡片「更多」按钮（list.tsx SpecCardList）、概览项目卡「进入」「更多」按钮（ProjectCards.tsx）、spec 详情「文档」Typography.Link（detail.tsx）、运维记录「查看处置过程」按钮（activities/index.tsx）。≥768px 视口该类 SHALL NOT 生效。

#### Scenario: 移动端命中区扩展
- **WHEN** 390px 视口下测量 SPEC 列表卡片「更多」按钮的可点击命中区
- **THEN** 命中区高度 ≥32px，且按钮视觉位置与相邻元素间距与未加类前一致（负 margin 抵消）

#### Scenario: 内联 padding 冲突处理
- **WHEN** 「查看处置过程」按钮既有内联 `padding: 0, height: 'auto'` 与工具类 padding 冲突
- **THEN** 实施时将该按钮内联样式调整为与工具类兼容的形式，命中区仍 ≥32px 且视觉不变形

#### Scenario: PC 端不受影响
- **WHEN** 视口宽度 ≥768px
- **THEN** `.touch-expand` 规则不命中，四处链接命中区与现状一致

### Requirement: SPEC 列表卡片已完成态进度单一表达
SpecCardList（仅移动端分支）中任务进度 ≥100% 的卡片 SHALL 在进度行右侧显示语义文本「已完成」，替代与进度条及 done/total 重复的百分比数字；未完成卡片仍显示百分比。桌面端表格进度列 SHALL 保持 done/total + 百分比双表达不变。

#### Scenario: 已完成卡片单一表达
- **WHEN** 390px 视口查看任务全部完成的 SPEC 卡片
- **THEN** 进度行右侧显示「已完成」，不再出现「100%」数字

#### Scenario: 未完成卡片表达不变
- **WHEN** 390px 视口查看任务进行中的 SPEC 卡片（如 5/8）
- **THEN** 进度行右侧显示「63%」百分比，左侧显示 5/8

#### Scenario: 桌面表格不变
- **WHEN** ≥768px 视口查看 SPEC 表格
- **THEN** 进度列仍为 done/total + 百分比双表达，与基线一致
