# 回归页签概览按钮移动端纵排

<!-- knowledge: capability=mobile-regression-actions-stacking rev=1
     sources=spec/knowledge/_inbox/done/mobile-ui-fixes-1107.md -->

项目详情测试回归页签（RegressionTab）概览操作区在窄屏视口下的纵排契约：三枚概览按钮 <768px 全宽纵排、桌面横排右对齐；现产项目详情页与 v2 项目详情页共用本组件，两侧同时生效。

## 规则

- **overviewActions 移动形态**：RegressionTab 的 `overviewActions` 纯渲染单元提供 `mobile?: boolean` 形态参数——<768px 视口传 `mobile` 时按钮容器为 `<Space direction="vertical">` 纵排，三枚概览按钮逐个 `block` 全宽（同页筛选 Drawer 页脚 block 按钮习语）；span Tooltip 承载层随之转 block（否则内层按钮 block 撑不满行宽）。
- **桌面缺省横排**：不传 `mobile`（≥768px 桌面视口）时概览按钮保持横排右对齐形态。
- **共用组件单点生效**：`overviewActions` 为纯渲染单元，projects/detail 回归页签消费本组件，移动端纵排随组件生效，页面不得各自另写按钮行。（原与 v2/projectDetail 共用，该页 2026-11-07 退役后仅存现产消费方。）

## 溯源

- 2026-11-07 mobile-ui-fixes-1107（spec/knowledge/_inbox/done/mobile-ui-fixes-1107.md） — 新建本页：折叠回归页签概览三按钮移动端纵排（overviewActions mobile 形态、block 全宽、span Tooltip 承载层转 block、桌面缺省不变、共用组件两侧生效）
