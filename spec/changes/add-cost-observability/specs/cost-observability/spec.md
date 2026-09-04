# cost-observability 增量规格

## ADDED Requirements

### Requirement: run 级 usage 提取与累计
实现/验证/裁决 run 收工时，系统 MUST 从 stream-json 输出提取最终 usage（input_tokens、cache_creation_input_tokens、cache_read_input_tokens、output_tokens）并累加到 STATE.md 对应 spec 的 `_tokens_in` / `_tokens_out` 内部字段（跨重启持久）。usage 缺失（run 异常早夭）时按 0 计并记日志。

#### Scenario: 修复轮累计
- **GIVEN** spec 已累计 26M input
- **WHEN** 下一次实现 run 收工（本次 14.5M）
- **THEN** `_tokens_in` 更新为 40.5M 并在 STATE.md 可见

### Requirement: Dashboard 与报告展示
Dashboard SPEC 详情 MUST 展示该 spec 的累计 token（格式如「输入 42.0M / 输出 0.3M」）；验证报告 MUST 含本验证链（planner+judge+scene 相关 LLM run）的增量 token 小节。

#### Scenario: 详情页可见
- **WHEN** 打开某 spec 详情
- **THEN** 治理字段区展示累计 token 数

### Requirement: 预算阈值告警
配置 `agents.token_budget_millions`（缺省 50，0=关闭）。累计 input 达到预算 80% 或 100% 时均发警告级 human-escalation-alerts 告警（一次性，不重复，2026-09-01 用户降噪决策：100% 线不再发严重事件）。告警 MUST NOT 自动冻结 spec。

降噪分级（2026-09-01）：预算告警中仅 critical/major（严重/较高）进人工待处理队列；warning/minor（警告/较低）写入即默认标记人工已处理——仍留历史记录，不弹 Dashboard 待处理横幅（`impl_budget_exempt_loop` minor 同此规则，`impl_budget_exhausted` major 保持人工）。

#### Scenario: 阈值触发一次
- **GIVEN** 预算 50M，已累计 40M
- **WHEN** 下次 run 收工累计越过 40M 线
- **THEN** 发送 80% 提醒告警，且后续 run 不重复发送（直到 100% 线）
- **AND** spec 状态不受影响

### Requirement: 金额展示不伪造
仅当 run 结果含成本字段时展示金额；缺失时展示「成本不可用（网关未回传）」而非 $0.00。

#### Scenario: 无成本字段
- **WHEN** 网关未回传 total_cost_usd
- **THEN** 界面显示 token 数与「成本不可用」标注
