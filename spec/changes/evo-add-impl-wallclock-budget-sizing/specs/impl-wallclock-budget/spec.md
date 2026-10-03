# impl-wallclock-budget 规格

## ADDED Requirements

### Requirement: impl 车道墙钟预算 sizing
系统 SHALL 支持按 spec 规模（任务数等，复用轮数 sizing 的规模判定）在派发前抬升 impl 车道的墙钟续期预算（max_extensions 档位），只抬不压、配置与覆盖键可干预。

#### Scenario: 大规模 spec 抬升续期预算
- **WHEN** impl run 的 spec 规模超过 sizing 阈值
- **THEN** 墙钟 max_extensions 按档位抬升（仿 fast-track higher 档先例），小规模 run 保持缺省

#### Scenario: 覆盖与关闭
- **WHEN** STATE 覆盖键或配置显式指定墙钟 sizing
- **THEN** 覆盖值优先；关闭时扩容行为与现状逐位一致

### Requirement: 墙钟扩容判定纳入剩余任务数
_supervision_deadline_action 的扩容/击杀判定 SHALL 评估「剩余任务数 vs 剩余续期预算」，extend/kill evidence 与 timeout_extension 事件 SHALL 携带 remaining_tasks。

#### Scenario: 仍有大量剩余任务时优先扩容
- **WHEN** 墙钟到期且 remaining_tasks 显著非零且扩容预算未耗尽
- **THEN** 优先扩容而非击杀，evidence 记录剩余任务数

#### Scenario: 扩容预算耗尽
- **WHEN** 扩容次数用满且剩余任务仍非零
- **THEN** 击杀，evidence 记「extension budget exhausted」并附 remaining_tasks

### Requirement: 击杀用量缺失显式化
击杀类终止 SHALL 在 run 档案落「用量缺失注记」：标明 token/cost 不可得及原因，并记录 transcript 规模类粗估维度，不得静默留空。

#### Scenario: 击杀 run 的用量注记
- **WHEN** run 被墙钟击杀且无 CLI result 事件
- **THEN** run_metrics 附用量缺失注记（原因=provider 无逐轮上报，附 transcript 字节数/轮数粗估维度），成功路径落盘行为不变