<!-- knowledge: capability=mobile-touch-targets rev=1 sources=spec/archive/2026-09-13-fix-mobile-touch-disclosure -->

# 触控目标尺寸

移动端小字链接触控目标的扩展机制与落地位置契约：`.touch-expand` 工具类在视觉零变化前提下把命中区扩到 ≥32px；含 SPEC 列表卡片已完成态进度单一表达。

## 规则

- 工具类定义：global.less 在移动端作用域定义 `.touch-expand`：`display:inline-block; padding:8px; margin:-8px`，使命中区扩展至 ≥32px（≥ WCAG 2.5.8 AA 最低 24×24），负 margin 完全抵消 padding，视觉与布局零变化。≥768px 视口该类不生效。
- 落地位置（四处小字链接）：SPEC 列表卡片「更多」按钮（`list.tsx` SpecCardList）、概览项目卡「进入」「更多」按钮（`ProjectCards.tsx`）、spec 详情「文档」Typography.Link（`detail.tsx`）、运维记录「查看处置过程」按钮（`activities/index.tsx`）。
- 内联样式兼容：落地处内联 padding/height 与工具类冲突时（如「查看处置过程」按钮），内联样式调整为与工具类兼容的形式，命中区保持 ≥32px 且视觉不变形。
- 已完成态进度单一表达：SpecCardList（仅移动端卡片分支）中任务进度 ≥100% 的卡片，进度行右侧显示语义文本「已完成」，不重复显示与进度条及 done/total 冗余的百分比数字；未完成卡片左为 done/total、右为百分比。桌面表格进度列保持 done/total + 百分比双表达。

## 溯源

- [2026-09-13 fix-mobile-touch-disclosure](spec/archive/2026-09-13-fix-mobile-touch-disclosure/) — 建立 `.touch-expand` 工具类（padding 8px + 负 margin 抵消，命中区 ≥32px）及其四处落地，并定案移动端卡片已完成态进度「已完成」单一表达
