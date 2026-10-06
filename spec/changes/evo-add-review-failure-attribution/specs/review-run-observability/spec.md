# review-run-observability Specification

## Purpose

评审类车道 run 失败可就地归因：错误日志行自带 exit_code/api_error_status/stderr_tail 归因括注；同型失败（如限流 0 成功轮）在 daemon_errors 聚合里同指纹可跨日追踪；熔断「连续失败」计数在成功后清零，不再被陈旧计数误触。

## Requirements

### Requirement: 评审失败行带结构化归因

评审 run 失败的 ERROR 日志行 MUST 附加 api_error_status、exit_code 与 stderr_tail 括注，形态与 code-fix 车道一致；归因字段经 AgentRunResult 透传。

#### Scenario: 限流失败就地归因

- **WHEN** 评审 run 因 API 限流失败退出
- **THEN** ERROR 行含 api_error_status=429（或对应状态码）与 stderr_tail 摘要，无须翻归档 run 文件即可归因

### Requirement: 同型失败同指纹

指纹归一化 MUST 对评审失败行模板剥离内嵌 SPEC 名段，使不同 SPEC 的同型失败聚到同指纹；其他组件的错误文字骨架不受影响。

#### Scenario: 跨 SPEC 聚合

- **WHEN** 两个不同 SPEC 的评审 run 发生同型失败
- **THEN** 归一化后指纹相同，可触发既有同指纹升级召唤

### Requirement: 熔断计数成功清零

评审 run 成功收工 MUST 调用 record_success 清零连续失败计数；「连续 infra 失败」语义恢复为窗口内连续。

#### Scenario: 陈旧计数不再误触

- **WHEN** 距上次评审成功已多日，其间偶发 1 次失败
- **THEN** 计数从 0 起算，不触发熔断