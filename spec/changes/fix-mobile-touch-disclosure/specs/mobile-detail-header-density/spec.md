## ADDED Requirements

### Requirement: 移动端隐藏顶栏全局面包屑
<768px 视口下，顶栏右侧的全局面包屑（app.tsx `HeaderCrumb`，经 `actionsRender` 注入）SHALL 隐藏（`display:none`，组件加 `global-header-crumb` className 作为选择器锚点）——spec 详情页头部已有返回箭头 + SPEC 名，面包屑在窄屏语义重复。≥768px 视口面包屑 SHALL 正常显示。

#### Scenario: 移动端详情页顶部两层
- **WHEN** 390px 视口打开 spec 详情页
- **THEN** 顶栏右侧不渲染面包屑（「概览 / fenixd / spec 名」不可见），页面头部为返回箭头 + SPEC 名 + Tag 行两层结构

#### Scenario: PC 端面包屑保留
- **WHEN** 视口宽度 ≥768px 打开 spec 详情页
- **THEN** 顶栏右侧面包屑正常显示，与基线一致（重点对照项）

### Requirement: 详情页标题 Tag 行窄屏换行
spec 详情页 headerCfg title 的 Space 容器（SPEC 名 + 模式 Tag + 状态 Tag + 切换下拉）SHALL 允许换行（`wrap`），390px 视口下不横向溢出。桌面端内容不溢出时 flex-wrap 无视觉差异。

#### Scenario: 移动端 Tag 行不溢出
- **WHEN** 390px 视口打开长名称 SPEC 的详情页
- **THEN** SPEC 名与 Tag 们自然换行显示，页面 `scrollWidth` 不超过 390，无横向溢出
