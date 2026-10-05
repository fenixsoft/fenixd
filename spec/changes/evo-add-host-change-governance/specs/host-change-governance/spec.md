## ADDED Requirements

### Requirement: 宿主系统级变更备份与登记

agent 对宿主系统级变更（内核模块、dkms、系统包、设备节点）MUST 先备份原版本（文件路径+版本+加载参数）并在 run 结果中登记；收工时若变更仍在位 MUST 附回滚指引；能用户态解决的 MUST NOT 动系统级。

#### Scenario: 变更前备份登记

- **WHEN** agent 准备替换/修改宿主内核模块
- **THEN** 原版本（路径+版本+参数）先备份并在 run 结果登记，变更后附回滚指引

### Requirement: 失败终态回滚义务告警

run 终态为失败（error/killed）且 run 结果含宿主变更登记时，框架自动向 admin 告警通道派发「回滚义务」告警，告警含变更清单与回滚指引；回滚执行由维护者/admin 人工裁决。

#### Scenario: 击杀 run 的宿主变更不丢失

- **WHEN** 含宿主变更登记的 run 被击杀
- **THEN** 框架派发回滚义务告警，修复义务不随 run 终态丢失

#### Scenario: 成功终态不告警

- **WHEN** 含宿主变更登记的 run 正常成功收工
- **THEN** 不派发回滚义务告警，登记仅作留痕