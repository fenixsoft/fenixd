# command-center-aggregation Spec

## MODIFIED Requirements

### Requirement: 裁决收件箱装配

聚合层 SHALL 提供裁决收件箱数据（`GET /api/command-center/inbox`）：收集未终态且告警记录携带 choices 快照的 admin_alerts 条目，每卡含告警 id、`project`、`spec`、`signal_type`、严重度、`narrative`（仅当告警已合并 narrative 槽位内容——历史侧车或 arbiter 报告——时携带；调查叙事生成链已退役，新告警不产生该字段）、`choices`（MUST 读告警记录内快照，MUST NOT 回读注册表演进态——与 add-human-adjudication-choices D2「历史告警不回写」语义一致）、`created_at` 与溯源字段（spec/run 链接）。响应 MUST NOT 携带 `narrative_pending` 字段（生成中态已随生成链退役）。按严重度降序、created_at 降序排列。本能力为只读装配：MUST NOT 新增裁决执行端点，执行复用既有 `POST /api/alert-resolve`。

#### Scenario: 待决卡片装配与排序
- **WHEN** admin_alerts 含：高严重度带 3 选项快照的未决告警、低严重度带选项快照的未决告警、已终态告警、无 choices 快照的知情类告警
- **THEN** 响应仅含前两条，高严重度在前；每卡 `choices` 与其告警记录内快照逐字段一致，且不含 `narrative_pending` 字段
- **THEN** 响应不包含任何执行动作端点引用，前端执行走既有 alert-resolve

#### Scenario: 项目筛选
- **WHEN** 以 `project=A` 请求
- **THEN** 仅返回项目 A 的待决卡

#### Scenario: 历史叙事随卡展示
- **WHEN** 一条待决告警存在退役前的历史侧车报告或 arbiter 报告
- **THEN** 该卡携带 `narrative` 字段；无槽位内容的卡不携带该字段且无任何生成中语义
