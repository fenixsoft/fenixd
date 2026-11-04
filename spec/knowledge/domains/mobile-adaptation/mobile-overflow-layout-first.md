<!-- knowledge: capability=mobile-overflow-layout-first rev=1
     sources=spec/knowledge/_inbox/done/memory-distill-user-rulings.md -->

# 移动端越界布局优先

窄屏越界治理的修复手法裁定：改布局、禁宽度微调、PC 端零影响。

## 规则

- 禁止宽度微调：移动端内容越界的修复 MUST NOT 通过微调宽度、压缩间距类数值硬凑，必须改布局承载——换行、改卡片形态、条件切换单列（条件 columns）等结构性手法。
- PC 端零影响：移动端越界修复不得改变 PC 端（≥768px 视口）的布局与观感；修复以移动端条件分支或媒体查询承载，PC 侧布局保持原样。

## 溯源

- 2026-11-04 memory-distill-user-rulings（spec/knowledge/_inbox/done/memory-distill-user-rulings.md） — 新建本页：折叠越界治理定调（改布局禁宽度微调、PC 零影响）
