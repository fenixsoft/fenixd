# v2-devserver-lifecycle 规格

## ADDED Requirements

### Requirement: 回退形态 dev-server 可归因
主树静态根回退形态启动的 v2 dev-server SHALL 携带可归因的 worktree 路径标记（argv 附加或 worktree static root 软链），使孤儿清扫的既有豁免逻辑能识别其在服状态。

#### Scenario: 在服 run 的回退形态 dev-server
- **WHEN** 非框架目标项目的 run 启动 dev-server（回退形态）且 run 在飞
- **THEN** 清扫周期不再产生 skip 告警，进程受既有豁免逻辑保护直至 run 结束

### Requirement: 清扫告警按 pid 记账去重
orphan sweep 对不可归因进程 SHALL 按 pid 记账：首见告警一次、后续静默计数；升级或处置判定 SHALL 以「无引用进程」为前提，MUST NOT 按裸存活时长自动 kill。

#### Scenario: 同 pid 重复扫描
- **WHEN** 同一不可归因 pid 在连续多个清扫周期存活
- **THEN** 仅首见告警，后续静默计数；确认无引用进程后才升级人工或处置

### Requirement: 告警文案与处置安全
skip 告警文案 SHALL NOT 给出无条件「可手动 kill」建议，SHALL 与归因/引用判定联动说明风险。

#### Scenario: 文案纠偏
- **WHEN** 产生回退形态 skip 告警
- **THEN** 文案说明判定局限与误杀在服 run 的风险，不诱导立即 kill

### Requirement: 重启后无主进程收口
daemon 重启 SHALL 能识别遗留 dev-server：可归因/有引用的保留，无主的收割或升级，防止端口池永久缩水。

#### Scenario: 重启对账
- **WHEN** daemon 重启后启动清扫发现遗留 dev-server
- **THEN** 按登记/argv 标记区分有主与无主，仅收割无主进程