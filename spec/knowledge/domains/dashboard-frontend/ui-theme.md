<!-- knowledge: capability=ui-theme rev=1 sources=spec/archive/2026-09-02-add-dashboard-theme-switch -->

# 界面主题切换

Dashboard 的黑/白双主题能力：配置页入口、全站即时切换与浏览器本地持久化。

## 现行规则

- 配置页页签栏提供「界面风格」页签，内含「黑色风格」「白色风格」两个单选；用户级与项目级配置页均可见且行为一致（主题是 Dashboard 全局属性，不随配置作用域变化）。未设置任何偏好时默认选中「黑色风格」。
- 主题选择不参与「保存配置」持久化：不写入 config.yaml 或任何 fenix 配置文件；选择即时生效并持久化到浏览器本地。
- 页签复用既有配置页页签模式（`tab-btn`/`tab-pane`），风格页签切换不影响其它页签的输入状态。
- 主题切换通过设置 `<html>` 根元素 `data-theme` 属性（`light`/`dark`）驱动 CSS 变量切换：浅色下根元素 `color-scheme` 为 `light`（原生控件、滚动条随之适配），深色保持 `dark`。切换不触发页面重载、不重新拉取任何 API、不改变页面内容与布局，跨视图即时生效。
- 主题偏好持久化在浏览器 `localStorage`（键 `fenix.theme`，取值仅 `dark`/`light`），每次切换立即更新；页面加载时由 `index.html` `<head>` 内联脚本（先于外部样式表、不依赖后加载脚本）在首帧绘制前应用主题，刷新后不出现「先深后浅」闪烁。取值缺失或非法时回退 `dark`；不使用服务端存储。
- 浅色与深色主题共用同一套 CSS 变量（`--page`、`--surface`、`--ink`、`--hairline`、状态色、分类色等），浅色调色板覆盖全部 UI 面：页面底色、卡片、内嵌块、三级文本、分隔线、顶栏、导航、页签、按钮、表单、表格、SPEC 状态徽标、timeline、模态遮罩与弹窗、banner、代码块；不出现白字灰底、白底白字等不可读组合，状态色与分类色在浅色背景上保持可辨识对比度。
- `style.css` 的颜色一律走 CSS 变量（或浅色作用域内变量派生覆盖），不散落硬编码色值；vendor 组件样式（如 react-vertical-timeline）由既有变量驱动的覆盖规则接管。
- 未显式设置时根元素默认深色；深色主题视觉为回归基准。

## 溯源

- 2026-09-02 add-dashboard-theme-switch（spec/archive/2026-09-02-add-dashboard-theme-switch） — 建立黑白双主题 CSS 变量体系、配置页「界面风格」入口、`data-theme` 全站即时切换、localStorage 持久化与首帧防闪烁契约
