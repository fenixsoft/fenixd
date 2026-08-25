# human-escalation-alerts Spec

## ADDED Requirements

### Requirement: 人工升级告警
当 Administrator 判断困境无法自主处置（如需要人类决策、连续处置失败、涉及不可逆操作需确认）时，SHALL 写入升级告警，包含：`id`、`created`、`severity`、`spec`、`description`、`evidence`、`action_taken`、`recommended_action`。Fenixd SHALL 将告警持久化到 `.fenix/admin_alerts.json`（gitignore）。

#### Scenario: 无法处置时升级
- **WHEN** Administrator 尝试处置后仍无法解决
- **THEN** 写入升级告警，记录明确的处置过程与建议

#### Scenario: 告警持久化
- **WHEN** 升级告警被写入
- **THEN** 告警保存到 `admin_alerts.json`，daemon 重启后仍可读取

### Requirement: Dashboard 人工介入通知
Dashboard SHALL 在存在未处理升级告警时，顶部显示醒目通知横幅（含未处理告警数、最高 severity、最新告警摘要），并提供告警列表与"标记已处理"操作。标记后横幅消失，告警保留可追溯。

#### Scenario: 打开 Dashboard 看到告警
- **WHEN** 存在未处理的升级告警，用户打开 Dashboard
- **THEN** 顶部横幅显示告警提示，可展开查看详情

#### Scenario: 标记已处理
- **WHEN** 用户查看告警后点击"标记已处理"
- **THEN** 告警状态更新为已处理，横幅消失
