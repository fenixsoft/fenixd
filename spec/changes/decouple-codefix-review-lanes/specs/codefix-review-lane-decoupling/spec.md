# codefix-review-lane-decoupling 能力

## ADDED Requirements

### Requirement: 批派发与审查在飞状态解耦

code-fix 车道的批派发与链推进 MUST NOT 以「周期审查 run 在飞」为否决条件或等待条件；code-fix 与审查的真实资源冲突点（回归主机级套件锁）由既有锁自然串行，逻辑调度层 MUST NOT 额外互斥。链的自驱动推进语义（`success`/`consumed` 均推进下一批）对**所有**批收尾路径成立，含延迟批（defer）合回路径——延迟批合回成功 MUST 等价于该批 `success` 收尾并推进下一批。

#### Scenario: 审查在飞期间照常派批

- **WHEN** 周期审查 run 长时间在飞（模拟慢/无产出），且 code-fix 台账存在 `open` 条目
- **THEN** code-fix 照常建树、派批、推进，MUST NOT 出现因审查在飞导致的派批空窗

#### Scenario: 延迟批合回后链继续

- **WHEN** defer 批经自动合回成功核销
- **THEN** 链 MUST 自驱动推进下一批（与常规批 `success` 收尾等价），MUST NOT 等待审查收尾事件或周期扫描才恢复

### Requirement: 审查 run stall 看门狗

周期审查 run 无产出超过阈值（进度产物 mtime 与进程 CPU 时间双判据同时达标；阈值 `admin.review_stall_minutes`，缺省 30）时，框架 SHALL 自动取消该 run 并走既有急救/落账路径（已完整落盘的产物抢救入账、告警留痕），释放其占用的车道与锁。看门狗 MUST NOT 误杀有进展的 run（任一判据显示进展即重置计时）。

#### Scenario: 僵死审查 run 被看门狗收走

- **WHEN** 审查 run 连续 30 分钟进度产物无 mtime 变化且进程 CPU 时间无增长
- **THEN** 看门狗取消该 run，已落盘产物走急救入账，告警留痕，code-fix 车道不被其牵连

#### Scenario: 有进展的 run 不被误杀

- **WHEN** 审查 run 进度产物持续更新（或 CPU 时间持续增长）
- **THEN** 看门狗不触发

### Requirement: 审查收尾激活语义保留

周期审查 run 正常收尾且 `inserted > 0` 时，既有两路激活（收尾触发 code-fix 链激活）语义 MUST 保留不变。

#### Scenario: 正常收尾仍激活链

- **WHEN** 审查 run 正常收尾且台账 `inserted > 0`
- **THEN** code-fix 链按既有语义被激活，行为与现状逐字一致
