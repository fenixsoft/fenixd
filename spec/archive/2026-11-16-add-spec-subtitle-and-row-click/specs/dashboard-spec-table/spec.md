# dashboard-spec-table Spec

## ADDED Requirements

### Requirement: 整行点击进详情

SPEC 列表行 SHALL 支持整行任意位置点击进入该 SPEC 详情页（镜像 overview 项目表格 `onRow` 整行点击范式：整行 `cursor: pointer` + 路由跳转）。行内既有交互 MUST NOT 被行点击吞并或误触发：展开钮（fix-* 树展开/收起、error 信息行展开）点击仍只做展开切换，操作列（⋯ 菜单、状态操作）点击仍只触发对应操作——交互单元格经事件守卫（stopPropagation 或目标判定）阻止行级导航；名称链接点击不额外拦截（链接自身导航与行导航同目标，连跳同路由、不产生错误页面，与 design D3 一致）；名称 Why 悬浮提示行为不变；展开行（expandedRowRender）内容区点击不触发导航。无 error 抑制语义（overview 的 error 守卫在 SPEC 列表无对应物，行恒可点）。

#### Scenario: 整行点击进详情

- **WHEN** 用户点击 SPEC 行的任务进度、耗时、状态等非交互单元格
- **THEN** 跳转进入该 SPEC 详情页，光标在行上为 pointer 形态

#### Scenario: 展开钮不触发导航

- **WHEN** 用户点击 fix-* 子行的展开钮（或 error 展开钮）
- **THEN** 仅展开/收起展开行，不发生路由跳转

#### Scenario: 操作列不触发导航

- **WHEN** 用户点击操作列 ⋯ 菜单或其中的状态操作项
- **THEN** 仅打开菜单/执行对应操作，不发生路由跳转

#### Scenario: 展开行内容区不触发导航

- **WHEN** 用户点击展开行内的清除按钮等内容控件
- **THEN** 仅执行对应操作，不发生路由跳转
