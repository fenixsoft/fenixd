# spec-transient-break-unseal-backoff

## ADDED Requirements

### Requirement: 解封后渐进恢复而非立即全量放行

core/agent_runner/provider_circuit.py 的全局瞬断熔断到期解封路径 MUST NOT 立即一次性放行全部积压：解封后 MUST 先进入 post-unseal hold（时长为 unseal_backoff_base_seconds×同指纹已解封次数，封顶 unseal_backoff_max_seconds），hold 期满先放行恰好一条最高优先级派发作为探针；同指纹解封次数 MUST 有状态记忆，并在稳定观察窗（无新熔断）后衰减复位。

#### Scenario: 解封不立即全量放行

- **WHEN** 全局瞬断熔断到期且队列存在多条积压
- **THEN** 先进入 hold，期满后仅放行一条最高优先级派发，其余积压 MUST 仍被持有

#### Scenario: hold 随解封次数渐进且封顶

- **WHEN** 同一指纹第二次解封
- **THEN** hold 时长为基数×2 且不超过封顶值

#### Scenario: 稳定后衰减复位

- **WHEN** 解封后稳定观察窗内无新熔断
- **THEN** 解封次数计数衰减复位，后续解封 hold 回到基数水平

### Requirement: 探针通过后按优先级错峰放行

探针派发的 provider 调用在观察窗内未再产生同指纹瞬断失败时，MUST 按既有队列优先级顺序（_run_queue 的 priority+aging）放行其余积压，MUST NOT 同拍全量并发放出；探针再失败时 MUST 按现行熔断规则重新冻结，且该指纹解封次数加一。

#### Scenario: 探针成功后错峰放行

- **WHEN** 探针 run 的 provider 调用在观察窗内未产生同指纹新失败
- **THEN** 其余积压按优先级顺序分批放行，无同拍全量并发

#### Scenario: 探针失败重回冻结

- **WHEN** 探针 run 再产生同指纹瞬断失败
- **THEN** 按现行规则重新冻结全部新派发，解封次数加一，告警链路照常

### Requirement: 配置与既有语义修订

新增 agents.transient_unseal_* 配置键（hold 基数/封顶/探针观察窗/稳定衰减窗），缺省启用、数值保守，经 core/config.py 规范化；tests/test_transient_backoff.py 中锁定「到期即清零重计」与「解封立即唤醒派发」的既有用例 MUST 同步修订到新语义（清零语义保留，立即全量唤醒改为 hold+探针），其余退避层用例 MUST NOT 改动。

#### Scenario: 配置键生效

- **WHEN** 修改 agents.transient_unseal_* 任一键
- **THEN** 对应 hold/观察窗/衰减行为随 30 秒热更新生效

#### Scenario: 既有退避层不受影响

- **WHEN** 非 解封节奏 相关的退避场景（原地 30/60/120、per-spec 600s 延迟）重放
- **THEN** 行为与现状逐字节一致
