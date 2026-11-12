# ops-alert-badge Spec

## ADDED Requirements

### Requirement: 运维菜单告警徽标计数

侧栏「运维」菜单项 SHALL 在存在待人工裁决告警时显示红点数字徽标。计数口径：未处理（未标记已处理、未失效 superseded）且携带非空裁决 `choices` 的告警条数；知情类告警（无 choices）与已处理/已失效告警 MUST NOT 计入。计数 MUST 与运维页告警数据同源（`GET /api/alerts` 跨项目聚合口径，含夹具告警过滤）。徽标随菜单项常驻展示，不依赖概览页或运维页处于激活态。

#### Scenario: 待裁决告警计数
- **WHEN** 存在 2 条未处理且携带 choices 的告警与 3 条未处理的知情类告警（无 choices）
- **THEN** 运维菜单项显示红点数字「2」，知情类不计入

#### Scenario: 标记已处理后计数递减
- **WHEN** 用户在运维页对一条待裁决告警标记已处理（或裁决执行成功）
- **THEN** 徽标计数同步递减；计数归零后徽标消失（不显示「0」）

#### Scenario: 已失效告警不计数
- **WHEN** 一条携带 choices 的告警被 superseded 标记失效
- **THEN** 该告警不计入徽标计数

### Requirement: 徽标实时刷新

徽标 SHALL 经 SSE 告警事件驱动刷新（事件合帧防抖）；SSE 不可用时 MUST 降级为周期轮询；页面不可见时 MAY 暂停、恢复可见时 MUST 补拉一次。刷新管线属壳级（跟随菜单常驻），MUST NOT 依赖概览页或运维页挂载。

#### Scenario: 新告警实时上徽标
- **WHEN** daemon 写入一条待裁决告警并推送 SSE 告警事件
- **THEN** 徽标计数在合帧窗口内更新（无需手动刷新页面）

#### Scenario: SSE 断连降级轮询
- **WHEN** SSE 连接断开且未恢复
- **THEN** 徽标按固定周期轮询刷新；连接恢复后回到事件驱动

### Requirement: 嵌入态豁免

`embed=1`（无侧栏菜单）模式下 MUST NOT 渲染徽标组件，且 MUST NOT 因此产生报错或控制台异常。

#### Scenario: 嵌入态无菜单无徽标
- **WHEN** Dashboard 以 embed 模式嵌入外部页面（menuRender 关闭）
- **THEN** 页面无侧栏亦无徽标，功能正常无报错
