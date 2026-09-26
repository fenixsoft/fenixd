## ADDED Requirements

### Requirement: 告警选择题交互

前端对带非空 `choices` 的告警 MUST 在告警卡片内渲染：选项下拉框（`Select`，label+desc）、可选备注输入框（note）、「执行」按钮。点击执行 MUST 调用 `POST /api/alert-resolve`，并按返回结果呈现：成功 → 该告警转为已处理态并提示处置结果摘要；失败 → 展示错误与已执行步骤说明，告警保持可重试。执行中按钮 MUST 处于 loading 态防重复提交。不带 `choices` 的告警保持既有「知道了」（markAlertHandled）交互，MUST NOT 出现下拉框。受影响组件：`core/dashboard/static/src/pages/projects/detail.tsx`（spec 详情告警区）与 `core/dashboard/static/src/pages/overview/components/AlertBanner.tsx`（overview 横幅）；服务层 `core/dashboard/static/src/services/dashboard.ts` 新增 `resolveAlert` 函数。

#### Scenario: 真裁决告警渲染下拉并可执行
- **WHEN** spec 详情页渲染一条携带 choices 的预算耗尽告警
- **THEN** 告警卡片出现下拉框（四个选项）、note 输入框与执行按钮；选择 force_advance 填写备注点击执行后，告警变为已处理并展示处置结果

#### Scenario: 知情类告警无下拉
- **WHEN** 渲染一条不带 choices 的 stale_code 告警
- **THEN** 卡片只有既有「知道了」按钮，无下拉框与执行按钮

#### Scenario: 执行失败可重试
- **WHEN** alert-resolve 返回错误（如动作执行异常）
- **THEN** 告警卡片展示错误信息与已执行步骤说明，下拉框与执行按钮恢复可交互状态，允许改选其他选项重试

### Requirement: 执行前确认与结果可见性

执行 `abandon`（撤销丢弃）与 `skip_review_gate`（跳过评审门）两类不可逆/降级动作时，前端 MUST 弹出二次确认（`Popconfirm` 或 Modal，desc 显示该动作后果与 note）；其余动作可直接执行。处置成功后 MUST 提示「处置留痕已写入 admin 活动记录」，保证人知道裁决已审计。

#### Scenario: 撤销动作二次确认
- **WHEN** 用户选择 abandon 点击执行
- **THEN** 出现二次确认弹层说明「撤销将丢弃该 spec 的工作，留痕后不可自动恢复」，确认后才发起 alert-resolve

#### Scenario: 处置成功提示留痕
- **WHEN** 任一选项执行成功
- **THEN** 成功提示中包含处置留痕已写入的说明
