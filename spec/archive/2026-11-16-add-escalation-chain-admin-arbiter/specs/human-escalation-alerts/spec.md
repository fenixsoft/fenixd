# human-escalation-alerts Spec

## MODIFIED Requirements

### Requirement: 人工升级告警

当处置链终点（Arbiter 失败/配额耗尽/黑名单信号/降级态）判定须人工出场时，SHALL 写入升级告警，包含：`id`、`created`、`severity`、`spec`、`description`、`evidence`、`action_taken`、`recommended_action`，并附全链痕迹（Admin 尝试痕、Arbiter 台账五段、链 run_id 族关联键）与剩余 choices。Fenixd SHALL 将告警持久化到 `.fenix/admin_alerts.json`（gitignore）。

升级边的首选消费者改为处置链（add-escalation-chain-admin-arbiter）：机器发起的冻结/升级信号默认入链（Admin 先行、Arbiter 拍板），链内任一级处置成功即终态化（resolved 附处置摘要与证据回链），不产生用户可感知告警（不推送、不进 pending、不落 admin_alerts 条目——处理中件以链状态/时间轴承载可见性）。仅链终点失败的上升件落人工队列（原告警落盘形态 + 全链痕迹）。黑名单信号与降级态（`arbiter.enabled: false` 或链失能）直达人工队列，行为与既有语义一致。人工冻结（freeze_spec）、定时冻结（frozen_until）不进链，行为与既有语义一致。

#### Scenario: 无法处置时升级

- **WHEN** Arbiter 调查后无法解决（自判失败或配额耗尽）
- **THEN** 写入升级告警，附全链痕迹与明确的处置建议

#### Scenario: 告警持久化

- **WHEN** 升级告警被写入
- **THEN** 告警保存到 `admin_alerts.json`，daemon 重启后仍可读取

#### Scenario: 链内成功零人工感知

- **WHEN** 机器冻结触发的升级信号被 Admin 或 Arbiter 链上自主处置成功
- **THEN** 不落 admin_alerts 条目、不进 pending、不推送；可见性由时间轴/处置链视图承载

#### Scenario: 上升件携带全链痕迹

- **WHEN** 链终点失败产生上升件
- **THEN** 告警条目含 Admin 尝试痕、Arbiter 台账关联与链 run_id 关联键，人工处置后可全链回溯

#### Scenario: 人工冻结路径不受扰

- **WHEN** 用户执行人工冻结且链启用
- **THEN** 不派发链，告警等待人工处置，与既有行为一致
