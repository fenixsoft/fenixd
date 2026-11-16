# delivery-push-integrity Specification

## ADDED Requirements

### Requirement: 推送目标为实际基分支

收尾与归档推送 MUST 推送项目的实际集成分支（检出分支或经基分支探测得到的 base ref），MUST NOT 硬编码固定分支名；推送成功判定 MUST 校验该分支的远端 tip。

#### Scenario: master 检出项目推送 master

- **WHEN** 项目检出分支为 master（无本地 main 工作流）
- **THEN** 收尾推送目标为 master，推送后 origin/master tip 前进

#### Scenario: main 检出项目行为不变

- **WHEN** 项目检出分支为 main
- **THEN** 推送目标与现状一致（main），行为无回退

### Requirement: 推送成功须断言 tip 前进

推送成功 MUST 以「远端 tip 前进（推送前后 SHA 比对）」为准；Everything up-to-date 空转 MUST NOT 计为成功，且 MUST 发单条告警（说明推送目标无新内容）。

#### Scenario: 空转推送被识别并告警

- **WHEN** 推送返回成功但远端 tip 未前进（up-to-date）
- **THEN** 不标记 delivered/pushed 终态，发一条空转告警（含本地/远端 tip 信息）

#### Scenario: tip 前进正常收口

- **WHEN** 推送后远端 tip 前进
- **THEN** 按现有流程标记 pushed 并收口

### Requirement: 启动时本地领先对账

daemon 启动时 MUST 对账本地集成分支相对远端的领先提交数并上报（日志/数据面），使判据失明期的静默缺口可见。

#### Scenario: 领先缺口启动即暴露

- **WHEN** 本地基分支领先其远端 N 个提交（N>0）
- **THEN** 启动对账输出领先数与分支名，供人工与聚合面消费