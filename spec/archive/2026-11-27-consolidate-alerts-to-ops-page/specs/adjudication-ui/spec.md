# adjudication-ui Spec

## MODIFIED Requirements

### Requirement: 告警选择题交互

前端对带非空 `choices` 的告警 MUST 在告警卡片内渲染：选项下拉框（`Select`，label+desc）、可选备注输入框（note）、「执行」按钮。点击执行 MUST 调用 `POST /api/alert-resolve`，并按返回结果呈现：成功 → 该告警转为已处理态并提示处置结果摘要；失败 → 展示错误与已执行步骤说明，告警保持可重试。执行中按钮 MUST 处于 loading 态防重复提交。不带 `choices` 的告警保持既有「知道了」（markAlertHandled）交互，MUST NOT 出现下拉框。裁决承载面（概览横幅退役后）：`core/dashboard/static/src/pages/projects/detail.tsx`（spec 详情告警区）、`core/dashboard/static/src/pages/activities` 运维页移动端告警行（MobileAlertRow，既有闭环）、指挥中心裁决收件箱卡；服务层 `core/dashboard/static/src/services/dashboard.ts` 的 `resolveAlert` 函数不变。运维页告警记录的桌面列表行按用户决策保持现状展示面（条目信息 + 报告入口 +「标记已处理」），MUST NOT 因本变更新增或移除裁决控件。

#### Scenario: 真裁决告警渲染下拉并可执行
- **WHEN** spec 详情页渲染一条携带 choices 的预算耗尽告警
- **THEN** 告警卡片出现下拉框（四个选项）、note 输入框与执行按钮；选择 force_advance 填写备注点击执行后，告警变为已处理并展示处置结果

#### Scenario: 概览横幅不再承载裁决
- **WHEN** 存在携带 choices 的未处理告警且用户打开概览页
- **THEN** 概览页无横幅亦无任何裁决下拉/执行控件（裁决入口仅详情页、运维页移动端行、指挥中心收件箱）

#### Scenario: 知情类告警无下拉
- **WHEN** 渲染一条不带 choices 的 stale_code 告警
- **THEN** 卡片只有既有「知道了」按钮，无下拉框与执行按钮

#### Scenario: 执行失败可重试
- **WHEN** alert-resolve 返回错误（如动作执行异常）
- **THEN** 告警卡片展示错误信息与已执行步骤说明，下拉框与执行按钮恢复可交互状态，允许改选其他选项重试
