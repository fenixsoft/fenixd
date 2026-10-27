## ADDED Requirements

### Requirement: 新验证流程连续降级熔断

同一 spec 的新验证流程（三阶段）因失败降级到 legacy verifier 时，框架 MUST 维护连续降级计数：**首次**降级维持既有行为（降级派发 legacy + WARNING）；**连续第 2 次**降级 MUST NOT 自动派发 legacy verifier，改 blocked + 升级告警，告警文案 MUST 附两次降级的原因链。连续降级计数随成功验证轮、admin 处置或人工解冻清零（与既有验证计数清零口径一致）。

#### Scenario: 首次降级维持既有
- **WHEN** 同一 spec 新验证流程首次失败（如 worktree 竞争类失败重入仍败）
- **THEN** 维持既有降级路径：派发 legacy verifier + WARNING 留痕

#### Scenario: 连续第 2 次降级转人工
- **WHEN** 同一 spec 连续第 2 次到达「新验证流程失败 → 降级」决策点
- **THEN** 不派发 legacy verifier，SPEC 转 blocked + 升级告警，文案含两次降级原因链；不产生第三轮静默降级

#### Scenario: 计数清零口径
- **WHEN** 降级熔断后经成功验证轮 / admin 处置 / 人工解冻恢复
- **THEN** 连续降级计数归零，后续首次失败重新获得既有降级机会
