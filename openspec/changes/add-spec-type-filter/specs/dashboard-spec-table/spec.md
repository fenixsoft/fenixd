## ADDED Requirements

### Requirement: 按类型过滤（全部/仅需求/仅问题）

系统 SHALL 在项目视图过滤栏提供类型下拉框，包含三个选项：「全部 / 仅需求 / 仅问题」，默认「全部」且不改变当前显示方式。「仅需求」SHALL 隐藏名称以 `fix-` 开头的全部 SPEC（含无父级分组行与其子树）；「仅问题」SHALL 仅显示名称以 `fix-` 开头的 SPEC。类型过滤 SHALL 与既有名称关键字、状态过滤叠加生效（AND 组合），过滤不改变列表排序。类型过滤 SHALL 为纯前端实现，不发起新的服务端请求。

#### Scenario: 默认选项为全部且不改变显示
- **WHEN** 打开项目视图且类型下拉为「全部」
- **THEN** 列表与当前显示方式一致，同时包含普通 SPEC 与 `fix-` 开头的 SPEC

#### Scenario: 仅需求隐藏 fix 系 SPEC
- **WHEN** 类型下拉选择「仅需求」，项目同时存在 `add-a` 与 `fix-b`（且 `fix-b` 下挂有子 SPEC `fix-fix-b`）
- **THEN** 列表仅显示 `add-a`，不显示 `fix-b` 及其子树 `fix-fix-b`

#### Scenario: 仅问题只显示 fix 系 SPEC
- **WHEN** 类型下拉选择「仅问题」，项目存在 `add-a` 与 `fix-b`
- **THEN** 列表仅显示 `fix-b`，不显示 `add-a`

#### Scenario: 仅问题视图下 fix 树层级保持
- **WHEN** 类型下拉选择「仅问题」，项目存在 `fix-a` 与 `fix-fix-a`
- **THEN** `fix-fix-a` 仍作为 `fix-a` 的子行展示（层级缩进关系保持）；基名 SPEC 不在结果中的 `fix-a` 归入「无父级」分组展示

#### Scenario: 与名称、状态过滤组合
- **WHEN** 类型「仅问题」、名称输入 `multi`、状态选择 `done`，项目存在 `fix-multi-x`（done）、`fix-other-y`（done）、`add-multi-z`（done）
- **THEN** 仅显示名称含 `multi`、状态为 `done` 且以 `fix-` 开头的 `fix-multi-x`

#### Scenario: 类型过滤与关键词过滤组合为空时显示空态
- **WHEN** 类型「仅需求」且名称输入一个仅存在于 `fix-*` SPEC 名中的关键字
- **THEN** 展示「无匹配的 SPEC」空态，区别于「该项目暂无 SPEC」

#### Scenario: 自动刷新后类型选择保持
- **WHEN** 类型下拉选择「仅需求」，随后发生 2 秒自动刷新
- **THEN** 下拉仍显示「仅需求」，表格仍按该条件过滤展示，控件回填保持选择值