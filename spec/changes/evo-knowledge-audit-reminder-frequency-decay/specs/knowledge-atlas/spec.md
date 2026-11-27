# 能力：知识体检聚合提醒降频（knowledge-atlas）

## ADDED Requirements

### Requirement: 超期未消费提醒降频

escalated 聚合提醒在最长龄期超过阈值天数（`knowledge.escalated_stale_days`，缺省 7，与 disputed 注记同口径）且持续零仲裁消费超过同一阈值后，MUST 降频为每 stale_days 天一拍（缺省即每周一拍）：距最近一次提醒落库不足 stale_days 时 MUST NOT 调用 todo 聚合行 upsert（保持旧行原文，MUST NOT 以空串触发纯清理删除聚合行），提醒文案 MUST 注明「已降频为每周一拍、欠账仍在」。降频期间 escalated 指纹集合发生新增或减少时 MUST 旁路降频当日拍出。

#### Scenario: 超 7 天未消费降频

- **WHEN** escalated 聚合提醒连续超 7 天零消费，且距上次提醒落库不足 7 天
- **THEN** 本轮不调用 upsert，todo 聚合行保持旧行原文，文案含降频注记，disputed 注记不变

#### Scenario: 降频期间新增 escalated

- **WHEN** 降频期间出现新的 escalated 指纹（指纹集合变化）
- **THEN** 当日体检收尾照常拍出聚合行（内容含新条目计数），不被降频抑制

#### Scenario: 状态键缺失或写失败

- **WHEN** 节拍状态键缺失/损坏，或 upsert 抛 OSError 降级
- **THEN** 本轮按应拍处理，且写失败不刷新最近提醒日期（下轮重试），MUST NOT 因此静默抑制提醒

### Requirement: 消费后节拍恢复

任一 escalated 指纹被仲裁消费（consume_arbitration 命中且 consumed 非空）后，MUST 恢复每日节拍，直至剩余疑点再次连续超过阈值天数零消费；全部消费后提醒按既有纯清理语义止拍并复位节拍状态键。消费判定、台账删除、disputed 注记摘除与自提交行为 MUST 保持不变（仅追加状态键记账）。

#### Scenario: 部分消费后恢复每日节拍

- **WHEN** 降频期间任一指纹被仲裁消费
- **THEN** 消费日重置零消费计时，随后体检每日拍出，按剩余疑点重新计数；超过阈值天数无消费后重新降频

#### Scenario: 全部消费后止拍

- **WHEN** escalated 全部被消费
- **THEN** 聚合行按既有纯清理语义摘除，节拍状态键复位

### Requirement: 欠账信号不丢失

降频期间 MUST NOT 影响：disputed 注记写入（core/knowledge_audit.py 既有 stale_days 逻辑）、todo 聚合行的存在性与原位替换语义、消费检查点行为；体检报告中的 escalated 汇总（`_escalated_summary`）MUST NOT 受节拍门控影响。

#### Scenario: 报告与注记口径不变

- **WHEN** 降频态下运行一轮体检
- **THEN** 报告中 escalated 汇总照常呈现，disputed 注记照常同步，todo 聚合行内容保持上次原文
