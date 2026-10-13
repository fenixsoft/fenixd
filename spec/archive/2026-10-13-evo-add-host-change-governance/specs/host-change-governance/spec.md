## ADDED Requirements

### Requirement: 宿主系统级变更备份与登记

agent 对宿主系统级变更（内核模块、dkms、系统包、设备节点）MUST 先备份原版本（文件路径+版本+加载参数）；登记以「变更发生时即时写入 worktree 根 host_changes.json 登记文件」为权威载体（击杀类终止无 run-result 时登记仍存活），收尾在 run 结果中汇总且两处一致；收工时若变更仍在位 MUST 附回滚指引；能用户态解决的 MUST NOT 动系统级。

#### Scenario: 变更前备份登记

- **WHEN** agent 准备替换/修改宿主内核模块
- **THEN** 原版本（路径+版本+参数）先备份，变更发生时即时写入登记文件并附回滚指引

### Requirement: 失败终态回滚义务告警

run 终态为失败（error/killed，含无 run-result 的击杀类终止：超时/轮次上限/判停）且宿主变更登记非空时，框架在 runner 终态记录点（先于 worktree 清理）读取登记文件，自动向 admin 告警通道派发「回滚义务」告警，告警含变更清单与回滚指引；回滚执行由维护者/admin 人工裁决。

#### Scenario: 击杀 run 的宿主变更不丢失

- **WHEN** 含宿主变更登记的 run 被击杀（无 run-result 产出）
- **THEN** 框架在终态记录点从登记文件派发回滚义务告警，修复义务不随 run 终态丢失

#### Scenario: 成功终态不告警

- **WHEN** 含宿主变更登记的 run 正常成功收工
- **THEN** 不派发回滚义务告警，登记仅作留痕