# agent-run-token-economy — run 级上下文经济性与缓存探针（新增）

## ADDED Requirements

### Requirement: 逐 run 上下文经济性指标与诊断告警

`_run_claude` SHALL 在其流式读取环内以**纯读侧**方式统计本次 run 的上下文经济性指标：轮数（assistant 事件数）、对话上下文峰值（token 估算）、累计 `input_tokens`、累计 `cache_read_input_tokens`。run 终结时（成功/失败/取消三路径）MUST 落一行结构化指标（日志 + run 转录），至少含 `run_id` / `turns` / `context_peak_tokens` / `per_turn_input_tokens`。

当 `per_turn_input_tokens` 超过配置阈值时，SHALL 打一条诊断 WARNING（含 run_id 与实测值），说明该 run 上下文成本接近 O(轮数²) 结构。该告警 MUST NOT 阻断 run、MUST NOT 触发独立人工告警（遵循告警降噪铁律）。指标的采集 MUST NOT 改变流式处理时序。

#### Scenario: run 结束落指标行
- **WHEN** 任意 agent run 正常结束
- **THEN** 日志与转录中出现含 `run_id` / `turns` / `context_peak_tokens` / `per_turn_input_tokens` 的指标行，可按 run_id 检索

#### Scenario: 超阈值打诊断告警且不阻断
- **WHEN** 某 run 的 `per_turn_input_tokens` 超过配置阈值
- **THEN** 出现诊断 WARNING（含 run_id 与实测值），且该 run 的终态判定与未超阈值时一致

#### Scenario: 不改变流式处理行为
- **WHEN** 流式事件到达
- **THEN** 事件处理时序与指标采集前一致（纯旁路，无阻塞/无重试逻辑变更）

### Requirement: 网关前缀缓存能力探针

框架 SHALL 提供可重复执行的探针 `bin/probe_prompt_cache.py`：对指定 provider 发送带 `cache_control` 的稳定前缀两轮请求，解析第二轮 `usage.cache_read_input_tokens`，输出确定性 JSON 判据（`provider` / `cache_supported` / `evidence`），用于判定该网关是否产生**可复用**前缀缓存命中。探针 MUST 可离线对配置内的任一 provider 单独执行，MUST NOT 依赖 daemon 运行。

探针的当前结论 SHALL 记录于 design，明确**本变更不做缓存优化**（网关不产生可复用命中）；探针保留以供网关升级后复验。

#### Scenario: 探针输出确定性判据
- **WHEN** 对某 provider 执行探针
- **THEN** 输出 JSON 含 `provider`、`cache_supported`（布尔）与 `evidence`（两轮 usage 摘要）

#### Scenario: 探针结论与实现解耦
- **WHEN** 探针结论为「不支持可复用缓存」
- **THEN** 框架 MUST NOT 因该结论改变 run 的派发/路由行为（结论仅作记录与复验依据，缓存优化明确不在本变更范围）
