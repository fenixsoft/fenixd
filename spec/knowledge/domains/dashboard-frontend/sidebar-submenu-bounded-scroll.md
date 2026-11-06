# 侧栏子菜单限高滚动与定制滚动条

<!-- knowledge: capability=sidebar-submenu-bounded-scroll rev=1
     sources=spec/knowledge/_inbox/done/antd-table-scroll-maxheight-sticky-th-1106.md -->

fenixd dashboard 独立访问形态（8787）左侧导航的 inline 子菜单限高滚动：超出约 5 项容器内滚动、滚动条按 dsh web 同款收窄定制；限高规则、锚点边界与滚动条量宽判据在本页。

## 规则

- **限高与 gutter**：`li.ant-menu-submenu > ul.ant-menu-sub.ant-menu-inline` 钉 `max-height: 200px; overflow-y: auto; scrollbar-gutter: stable`。200px = 5 项完整可见（单项内容 36px、布局占位 40px 含 4px 行距）；行距占位不计入 offsetHeight，校准须用 getBoundingClientRect 相对容器实测。
- **锚点唯一**：ProLayout 侧栏是全站唯一 antd inline 子菜单，settings/help 左目录自画不受波及；侧栏折叠态子菜单走浮层 `.ant-menu-vertical`，不命中本选择器。
- **展开动画共存**：展开动画期间 antd 用内联 height + overflow:hidden 驱动（内联优先级更高），动画结束内联移除后限高生效，互不干扰。
- **gutter stable 的作用**：overlay 滚动条引擎（Chromium Fluent 默认）下滚动条不占布局宽，stable 按 `::-webkit-scrollbar` 定制宽 6px 预留 gutter，滑块浮于 gutter 内不遮菜单文字；经典滚动条模式下与真实占宽冗余无害（防溢出/不溢出两态行宽跳动）。
- **定制滚动条五条**：同选择器 `::-webkit-scrollbar-*`——宽 6px、thumb 中性灰 alpha（rgba(127,127,127,.5)、hover .8，亮暗主题通用）、track 透明、button display:none（去 Chrome 默认上下箭头）。fenixd 无 dsh 的 scrollbar 变量体系，故用 alpha 灰而非官方变量色；规则限定同一选择器作用域，页面其他滚动条零波及。
- **守卫**：`tests/pageChrome.test.mjs` 钉选择器、200px 限高、gutter stable 与滚动条规则形态。

## 关键行为

- **滚动条量宽判据（headless Chromium 148 实测）**：该引擎 overlay 滚动条模式下滚动条不占布局宽——`::-webkit-scrollbar` 定制宽不改变 offsetWidth−clientWidth（全局规则同样无效）；量到的占宽实为 `scrollbar-gutter: stable` 按定制宽预留的 gutter，无 stable 的容器占宽恒 0。量滚动条宽须先问容器有无 gutter stable。视觉验证 headless 截图不渲染滚动条本体，以规则注入 + gutter 几何为证；真实桌面 Chrome 的 webkit 定制正常生效。
- **embed 模式不渲染侧栏**：dsh 面板桥（3080 嵌入）场景走宿主侧栏，本页规则只作用于独立访问形态，两者互不相干。

## 溯源

- 2026-11-06 antd-table-scroll-maxheight-sticky-th-1106（spec/knowledge/_inbox/done/antd-table-scroll-maxheight-sticky-th-1106.md） — 新建本页：fenixd 独立访问侧栏（8787）子菜单 5 项封顶 200px、gutter stable、定制滚动条中性灰 alpha 五条、锚点唯一与浮层不命中、动画内联优先、headless overlay 引擎滚动条量宽判据
