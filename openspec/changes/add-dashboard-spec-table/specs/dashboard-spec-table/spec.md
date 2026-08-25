## ADDED Requirements

### Requirement: 数据层暴露创建时间

系统 SHALL 在 `/api/specs` 的每个 SPEC 摘要项中提供 `created` 与 `updated` 字段（来自 `STATE.md` 条目的 ISO 时间字符串；条目缺失时为 `null`），供前端排序与展示使用。该新增字段 SHALL 不影响既有字段与既有消费方。

#### Scenario: 列表项包含 created 与 updated
- **WHEN** 请求 `GET /api/specs?project=<name>`
- **THEN** 每个 SPEC 摘要项包含 `created` 与 `updated` 字段，取值与 `STATE.md` 条目一致；无该字段的 SPEC 为 `null`

### Requirement: 按创建时间倒序排序

系统 SHALL 按 SPEC 创建时间倒序（新在前）返回与展示项目 SPEC 列表。服务端 `/api/specs` SHALL 以 `created` 倒序为默认排序，`created` 缺失的 SPEC 排到最后；前端 SHALL 以同一规则再次排序确认。倒序排序 SHALL 优先于其它排序键。

#### Scenario: 新创建的 SPEC 排在最前
- **WHEN** 某项目有创建时间分别为 T1、T2、T3（T3 最新）的 SPEC，请求项目 SPEC 列表
- **THEN** 列表顺序为 T3、T2、T1（新在前）

#### Scenario: 缺失创建时间的 SPEC 排最后
- **WHEN** 某 SPEC 的 `created` 缺失（`null`）
- **THEN** 该 SPEC 排在有创建时间条目的末尾，即使其名字或优先级更高

### Requirement: 表格化展示与表头说明

系统 SHALL 以带表头的表格展示项目 SPEC 列表。表头 SHALL 逐列说明含义，至少包含：状态、名称、优先级、创建时间、任务进度、验证、错误。每行 SHALL 保留既有交互与视觉（点击进入详情、状态 pill、进度条、错误 tag）；无创建时间的行显示占位符（如 `—`）；无验证进度的行验证列显示占位符。

#### Scenario: 表格带表头且每列有含义
- **WHEN** 打开项目视图
- **THEN** 渲染为 `<table>`，`<thead>` 含「状态 / 名称 / 优先级 / 创建时间 / 任务进度 / 验证 / 错误」表头，`<tbody>` 每行与表头列一一对应

#### Scenario: 行保留点击进详情与既有视觉
- **WHEN** 点击表格中的某 SPEC 行
- **THEN** 跳转到该 SPEC 详情视图，行内状态 pill、进度条、错误 tag 正常显示

### Requirement: 前端名称与状态过滤

系统 SHALL 在项目视图提供前端过滤：名称关键字输入框（大小写不敏感、包含匹配）与状态下拉框（「全部状态」或指定状态）。过滤 SHALL 作用于已按创建时间倒序排列的列表，保留排序顺序；过滤后为空 SHALL 展示「无匹配的 SPEC」空态，区别于「该项目暂无 SPEC」。过滤为纯前端实现，不发起新的服务端请求。

#### Scenario: 按名称关键字过滤
- **WHEN** 输入框输入 `fix`，项目存在 `fix-a` 与 `add-b`
- **THEN** 仅显示名称包含 `fix`（不区分大小写）的 `fix-a`

#### Scenario: 按状态过滤
- **WHEN** 状态下拉选择 `done`
- **THEN** 仅显示状态为 `done` 的 SPEC

#### Scenario: 名称与状态组合过滤
- **WHEN** 名称输入 `fix` 且状态选择 `done`
- **THEN** 仅显示名称含 `fix` 且状态为 `done` 的 SPEC

#### Scenario: 过滤结果为空
- **WHEN** 过滤条件组合无任何匹配 SPEC
- **THEN** 展示「无匹配的 SPEC」空态信息

### Requirement: 过滤状态在自动刷新间保持

系统 SHALL 在 2 秒自动刷新重渲染时保持过滤输入与选择状态不变：刷新仅更新表格数据，不得重置名称关键字与状态选择；重新渲染后过滤条件仍生效且控件回填当前值。

#### Scenario: 自动刷新后过滤条件仍生效
- **WHEN** 用户输入名称 `fix` 并选择状态 `done`，随后发生自动刷新
- **THEN** 输入框与下拉仍显示 `fix` 与 `done`，表格仍按该条件过滤展示
