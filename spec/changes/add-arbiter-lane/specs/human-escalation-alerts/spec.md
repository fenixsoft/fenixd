# human-escalation-alerts Spec

## MODIFIED Requirements

### Requirement: 人工升级告警
当 Administrator 判断困境无法自主处置（如需要人类决策、连续处置失败、涉及不可逆操作需确认）时，SHALL 写入升级告警，包含：`id`、`created`、`severity`、`spec`、`description`、`evidence`、`action_taken`、`recommended_action`。Fenixd SHALL 将告警持久化到 `.fenix/admin_alerts.json`（gitignore）。

升级边的首选消费者改为 Arbiter 优先、人工终审（add-arbiter-lane）：机器发起的冻结/升级（`freeze_for_human` 全族与 blocked/frozen/争议类 escalation alert）先经 Arbiter 调查——自主处置成功的，原告警由处置结果直接终态化（resolved_by=arbiter，附处置摘要与证据回链），不产生用户可感知告警（不推送、不进 pending）；处置不了/白名单外/死人开关触发的，裁决包（调查报告+处置选项+推荐）同 alert_id 原位静默更新（报告进 narrative 槽位、choices/推荐注入原条目）并推入 pending 人工队列，不新增告警条目。人工冻结（freeze_spec）、定时冻结（frozen_until）、token 预算耗尽、spec_integrity、queue 异常类告警不进 Arbiter 触发面，行为与既有语义一致；`arbiter.enabled: false` 时全部告警路径与现状逐字节一致。

#### Scenario: 无法处置时升级
- **WHEN** Administrator 尝试处置后仍无法解决
- **THEN** 写入升级告警，记录明确的处置过程与建议

#### Scenario: 告警持久化
- **WHEN** 升级告警被写入
- **THEN** 告警保存到 `admin_alerts.json`，daemon 重启后仍可读取

#### Scenario: Arbiter 处置成功告警终态化
- **WHEN** 机器冻结触发的升级告警被 Arbiter 自主处置成功
- **THEN** 该告警终态化为已处理（resolved_by=arbiter，附处置摘要回链），不进 pending、不推送、不新增条目

#### Scenario: Arbiter 升级裁决包原位挂靠
- **WHEN** Arbiter 判定须人类拍板（白名单外/处置失败/连败/预算耗尽）
- **THEN** 裁决包原位更新该告警（报告进 narrative 槽位、choices/推荐注入）并推入 pending，告警总条数不变

#### Scenario: 人工冻结路径不受扰
- **WHEN** 用户执行人工冻结且 Arbiter 车道启用
- **THEN** 不派发 Arbiter，告警等待人工处置，与既有行为一致
