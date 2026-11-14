# web 验证 element_visible 断言对祖先 overflow 裁剪不敏感

## 背景

consolidate-alerts-to-ops-page 验证（2026-11-12）徽标三场景全 pass，但 2026-11-13 用户实测侧栏「运维」徽标数字不可读——只剩一条红色小弧。缺陷在交付前就存在，断言网没有拦截。

## 结论（当前事实）

- verify-pipeline web 形态的 `element_visible` 断言（Playwright isVisible 语义）对「有非空 bounding box、但被祖先 `overflow:hidden/clip` 裁剪出可视区」的元素照样返回 true；`text_match` 断言的也是 DOM 文本而非渲染像素。**DOM 在场 ≠ 像素可读**，两者并存时三场景全 pass 与视觉不可读可以同时成立。
- 典型触发面：往 ProLayout / antd Menu 菜单项 name 里挂角标类绝对定位元素（Badge sup `translate(50%,-50%)` 悬出文本框）。菜单项文本容器 `ant-pro-base-menu-inline-item-text` 为 `overflow:hidden`（省略号裁剪），悬出部分全裁。
- 防线两条：
  1. **样式侧**：菜单/文本容器内挂角标一律走行内流（antd Badge 用 `style={{position:'static', transform:'none', display:'inline-block'}}` 内联压角标定位，antd v6 `style` 经 `mergedStyles.indicator` 直落 sup 本体），不依赖绝对定位+偏移。
  2. **断言侧**：涉及「渲染可见性」的场景，元素级断言后补一道几何自检（元素 rect 须完全落在最近 `overflow` 非 visible 祖先的 padding box 内），或直接以截图/像素断言承载。

## 证据

- 修复前取证：`.ant-badge-count` text="1"，rect (75,386,14,14)，`clipperAncestor="ant-pro-base-menu-inline-item-text"`，viewport 截图放大只见红弧无数字。
- 修复 commit：fenixd 763c8a591（app.tsx `OpsMenuName` sup 转行内流）；复验几何 `insideMenuItem:true`、`clippedByAncestorOverflow:false`。

## 溯源

- `spec/changes/consolidate-alerts-to-ops-page/verification-report.md` §8（交付后缺陷补记）
- `spec/knowledge/domains/verify-pipeline/`（断言分层语义）
