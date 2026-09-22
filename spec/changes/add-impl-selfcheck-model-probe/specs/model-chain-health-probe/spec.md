# model-chain-health-probe 能力增量（add-impl-selfcheck-model-probe）

> 拒模型快速 failover 契约：unrecognized_model 是确定性失败，立即沿链 failover，不再同因重派；模板默认链摘除实测拒模型条目。

## ADDED Requirements

### Requirement: unrecognized_model 识别与链上 failover

provider 返回 `unrecognized_model` 类错误（stderr 出现 `[claude-code:unrecognized_model]` 或等价结构化类别）时，框架 MUST 将其归类为确定性模型失败而非 provider-transient：①立即记 WARNING 告警（含 provider、model、run_id）；②沿该 agent 类型配置的模型链原地切换到下一个可用模型继续当前 run，MUST NOT 以同因重派方式重新派发整个 run，MUST NOT 递增 transient 熔断/同因重派计数；③链尾模型同样拒模型时按既有失败路径收场（此时失败归因须含「全链模型不可用」语义）。其余 provider 错误（5xx、超时、黑洞等）的处理路径 MUST 保持现状不变。

#### Scenario: 首选模型被拒立即 failover

- **WHEN** 某 impl run 首选 `maomaoai/deepseek-v4.1-flash` 发起首轮调用，provider 返回 unrecognized_model
- **THEN** 该 run 记 WARNING 后立即切换到链上下一个模型继续执行，run 不终止、不产生 r1 重派、同因重派计数不变

#### Scenario: 全链被拒按失败收场

- **WHEN** 某 agent 类型链上全部模型均返回 unrecognized_model
- **THEN** run 按既有失败路径终止，归因含全链模型不可用语义，后续处理走既有失败治理（非同因重派循环）

#### Scenario: 其他错误路径不变

- **WHEN** provider 返回 5xx 过载或连接超时（非 unrecognized_model）
- **THEN** 处理路径与未引入本能力前完全一致（transient 延迟重派等既有语义）

### Requirement: 模板默认链摘除无效模型条目

`.fenix/config.template.yaml`（入库模板）中各 agent 类型的默认模型链 MUST 删除 `provider: maomaoai, model: deepseek-v4.1-flash` 条目（全部出现处）。删除理由与恢复条件 MUST 写入运维文档；运行时 `.fenix/config.yaml` 的同步修改为人工运维步骤，MUST 登记到 `.fenix/todo.md` 提醒（不作为 tasks.md 门禁任务）。摘除后模板各链剩余条目数 ≥3，链尾 failover 语义不受影响。

#### Scenario: 模板链不再含拒模型条目

- **WHEN** 检查入库模板 `.fenix/config.template.yaml` 全部 agent 类型默认链
- **THEN** 无任何 `maomaoai + deepseek-v4.1-flash` 组合条目；implementer/planner/verifier 等链各自仍有 ≥3 个备选模型

#### Scenario: 人工步骤已登记

- **WHEN** 查阅运维文档与 `.fenix/todo.md`
- **THEN** 文档含摘除理由、恢复条件与运行时配置修改步骤；todo.md 存在对 `.fenix/config.yaml` 同步摘除的人工提醒条目
