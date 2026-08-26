# admin-activity-view Spec

## ADDED Requirements

### Requirement: 运维记录 API
Fenixd SHALL 提供 `GET /api/admin-activities?project=<name>`，返回该项目的 Administrator 活动记录列表（按时间倒序）。每条记录 SHALL 包含：时间（created）、spec、信号类型、严重度、叙述总结（summary）、处置动作（actions_taken）、结果（result）、是否升级（escalate）、人工建议（recommended_action）、未处理标记（handled）。跨项目聚合请求时按项目分组返回。

#### Scenario: 返回活动记录列表
- **WHEN** 请求 GET /api/admin-activities?project=<name>
- **THEN** 返回按时间倒序的 disposition 记录列表，每条含 summary/actions_taken/result/escalate/recommended_action/handled

#### Scenario: 未处理升级置顶
- **WHEN** 存在未处理的 escalation 记录
- **THEN** API 将未处理升级记录置于列表顶部

#### Scenario: 无记录返回空列表
- **WHEN** 该项目无任何 admin 活动记录
- **THEN** API 返回空列表且不报错

### Requirement: 运维记录独立页面
Dashboard SHALL 提供独立"运维记录"页面，展示 Administrator 全部活动，面向人类可读、逻辑清晰。页面 SHALL 以时间线展示每条记录：时间、spec、信号类型、叙述总结、处置动作、结果徽章、人工建议。未处理升级告警 SHALL 置顶高亮，并明确展示"需人工决策"的建议与 mark-handled 操作。

#### Scenario: 展示活动时间线
- **WHEN** 用户打开运维记录页面
- **THEN** 按时间倒序展示全部 admin 活动，每条含时间/事项/结果

#### Scenario: 未处理升级高亮置顶
- **WHEN** 存在未处理的升级告警
- **THEN** 该记录置顶并高亮，显示明确的"需人工决策"建议与 mark-handled 操作

#### Scenario: 旧记录无 summary 不崩溃
- **WHEN** 页面读取无 `summary` 字段的旧 disposition 记录
- **THEN** 页面降级显示结构化字段（actions_taken/result），不报错
