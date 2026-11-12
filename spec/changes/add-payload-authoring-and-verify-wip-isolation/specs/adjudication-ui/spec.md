# Spec Delta: adjudication-ui

## MODIFIED Requirements

### Requirement: 告警选择题交互

前端对带非空 `choices` 的告警 MUST 在告警卡片内渲染：选项下拉框（`Select`，label+desc）、可选备注输入框（note）、「执行」按钮。点击执行 MUST 调用 `POST /api/alert-resolve`，并按返回结果呈现：成功 → 该告警转为已处理态并提示处置结果摘要；失败 → 展示错误与已执行步骤说明，告警保持可重试。执行中按钮 MUST 处于 loading 态防重复提交。不带 `choices` 的告警保持既有「知道了」（markAlertHandled）交互，MUST NOT 出现下拉框。裁决承载面（概览横幅退役后）：`core/dashboard/static/src/pages/projects/detail.tsx`（spec 详情告警区）、`core/dashboard/static/src/pages/activities` 运维页移动端告警行（MobileAlertRow，既有闭环）、指挥中心裁决收件箱卡；服务层 `core/dashboard/static/src/services/dashboard.ts` 的 `resolveAlert` 函数不变。运维页告警记录的桌面列表行按用户决策保持现状展示面（条目信息 + 报告入口 +「标记已处理」），MUST NOT 因本变更新增或移除裁决控件。

**requires_payload 选项的载荷交互（本变更新增）**：当用户选中的选项经下拉框数据标注（选项元数据随 choices 下发，含 `requires_payload` 布尔与 `payload_schema` 摘要）判定为需载荷时，前端 MUST 以专用载荷编辑器替换普通 note 输入框：JSON 文本域 + 载荷形态提示（scenarios/reason/fixture_files 契约摘要与各字段语义）、客户端 JSON 语法校验（非法 JSON MUST 禁用执行按钮并就地报错）、空载荷或仅空白 MUST 拦截提交并提示必填。载荷来源 MUST 提供三态：①告警挂有草稿指针时预填草稿（`GET /api/alert-payload-draft` 只读取材，只读不写）；②无草稿时提示可等待起草（admin-payload-drafting 能力）或人工粘贴；③人工编辑内容优先于草稿（编辑后提交以编辑版为准）。提交前 MUST 展示执行前置清单：SPEC 冻结态（冻结时展示「须先解冻」并提供一键解冻前置按钮，调既有 unfreeze 接口成功后才放行执行）、场景修订预算余量（已用/上限）、载荷体积提示（超大载荷展示字节量）。执行按钮对 requires_payload 选项在载荷未过校验时 MUST 保持禁用。「按草稿执行」快捷入口仅在草稿在位且未过校验失败时可用。上述载荷交互 MUST 仅作用于 requires_payload 选项，普通选项交互形态与既有行为完全不变。视觉与组件规范遵循仓库根 DESIGN.md。

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

#### Scenario: 选中载荷选项出现编辑器并拦截空载荷
- **WHEN** 用户在修订类告警下拉中选中 revise_scenario_reverify（requires_payload=true）
- **THEN** note 输入框替换为 JSON 载荷编辑器（含形态提示），载荷为空或非法 JSON 时执行按钮禁用并就地报错；切回普通选项时恢复原 note 交互

#### Scenario: 草稿预填与按草稿执行
- **WHEN** 告警挂有草稿指针且用户打开载荷编辑器
- **THEN** 编辑器预填草稿全文，前置清单展示冻结态与预算余量；SPEC 冻结时一键解冻成功后执行按钮放行；点击「按草稿执行」直接以草稿载荷提交 alert-resolve

#### Scenario: 冻结前置清单阻断直接执行
- **WHEN** SPEC 处于用户指令冻结（error 以用户指令冻结前缀开头）且用户已填合法载荷点击执行
- **THEN** 前置清单标红冻结项，执行请求被前端拦截并提示先解冻；一键解冻成功后清单解除，执行按钮放行

#### Scenario: 普通选项零回归
- **WHEN** 用户在同一告警中改选非 requires_payload 选项（如 force_advance）
- **THEN** 交互回退为普通 note 输入框，既有校验与提交流程不变，无载荷编辑器残留
