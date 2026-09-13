## Why

概览页（overview）统计卡与项目清单在移动端存在空间浪费与内容截断：IntroduceRow 四张统计卡内联 `padding: 16px 24px` 未收紧、Card 卡头标题与卡内自绘灰眉题重复渲染（四卡各浪费一行）、Token 卡 `whiteSpace:'nowrap'` 致「平均每 SPEC 4…」数字注释溢出截断；项目清单卡头内 160px 定宽搜索框在 390px 视口下被挤压到不可用。移动端屏幕空间宝贵（用户明确要求充分利用），上述浪费在 390px 宽度下影响显著。

## What Changes

- `pages/overview/components/IntroduceRow.tsx`：网格容器、灰眉题、两处 nowrap 数字行加 className 钩子（其余全走 CSS，不改桌面样式）。
- `global.less` 移动端作用域追加：统计卡 body padding 收紧为 12px 16px、灰眉题 `display:none`（去重，保留卡头黑标题与 Tooltip 信息图标）、数字行允许换行（`!important` 压内联 nowrap/overflow，仓库 alert-banner 先例）。
- `pages/overview/components/ProjectCards.tsx`：项目清单 Card 加 className；移动端卡头标题与 extra（搜索框+状态过滤）分两行，搜索框撑满整行。

## Capabilities

### New Capabilities

- `mobile-overview-density`: 概览页统计卡与项目清单的移动端信息密度——去重复标题、收紧内边距、修复数字注释截断、搜索框全宽可用。

### Modified Capabilities

（无）

## Impact

- 受影响文件：`core/dashboard/static/src/pages/overview/components/IntroduceRow.tsx`（4 处 className）、`core/dashboard/static/src/pages/overview/components/ProjectCards.tsx`（1 处 className）、`core/dashboard/static/src/global.less`（尾部追加规则）。
- PC 端（≥768px）：className 无任何桌面规则命中，全部新规则限定在 `:is(.screen-xs,.screen-sm)` 作用域内（spec A `fix-mobile-breakpoint-hook-tables` 确立的作用域约定）。
- 无 API / 数据 / 依赖变更；纯展示层改动。
