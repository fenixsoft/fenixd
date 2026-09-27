<!-- knowledge: capability=mobile-detail-header-density rev=1 sources=spec/archive/2026-09-13-fix-mobile-touch-disclosure -->

# 详情页头部密度

spec 详情页头部在移动端的层级压缩契约：隐藏顶栏全局面包屑、标题 Tag 行允许换行，窄屏头部保持两层结构不溢出。

## 规则

- 顶栏面包屑移动端隐藏：<768px 视口下，顶栏右侧全局面包屑（app.tsx `HeaderCrumb`，经 `actionsRender` 注入）以 `display:none` 隐藏（组件挂 `global-header-crumb` className 作为选择器锚点）；≥768px 面包屑正常显示。
- 详情页头部两层结构：spec 详情页头部为返回箭头 + SPEC 名 + Tag 行，窄屏下不叠加顶栏面包屑。
- 标题 Tag 行换行：headerCfg title 的 Space 容器（SPEC 名 + 模式 Tag + 状态 Tag + 切换下拉）设置 `wrap` 允许换行；长名称 SPEC 在 390px 视口下自然换行，页面 `scrollWidth` 不超过视口宽度，无横向溢出。

## 溯源

- 2026-09-13 fix-mobile-touch-disclosure — 建立顶栏全局面包屑移动端隐藏（`global-header-crumb` 锚点）与详情标题 Space `wrap` 防溢出契约
