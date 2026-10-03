# impl-wallclock-budget 规格

## ADDED Requirements

### Requirement: impl 车道墙钟预算 sizing
系统 SHALL 支持按 spec 规模（任务数等，复用轮数 sizing 的规模判定）在派发前抬升 impl 车道的墙钟续期预算（max_extensions 档位），只抬不压、配置与覆盖键可干预。档位由 run 启动时点同源的 spec 总规模决定、对整次 run 恒定（每次 deadline 判定重复推导 MUST 幂等，MUST NOT 以 remaining_tasks 回算档位）；物化点沿 fast-track 先例落在 deadline 判定内，等价于派发前确定的生效预算。

#### Scenario: 大规模 spec 抬升续期预算
- **WHEN** impl run 的 spec 规模超过 sizing 阈值
- **THEN** 墙钟 max_extensions 按档位抬升（仿 fast-track higher 档先例），小规模 run 保持缺省

#### Scenario: 覆盖与关闭
- **WHEN** STATE 覆盖键或配置显式指定墙钟 sizing
- **THEN** 覆盖值优先；关闭时扩容/击杀判定决策与墙钟数值和现状逐位一致（判定 evidence/事件新增 remaining_tasks 字段为无条件观测增强，不受 sizing 开关影响）

### Requirement: 墙钟扩容判定纳入剩余任务数
_supervision_deadline_action 的扩容/击杀判定 SHALL 评估「剩余任务数 vs 剩余续期预算」，extend/kill evidence 与 timeout_extension 事件 SHALL 携带 remaining_tasks。remaining_tasks 为判定证据与复盘维度：既有封闭矩阵的分支结构与判定顺序（absolute_max 封顶 → 续期次数 → 活性/停滞）SHALL 保持不变，MUST NOT 以 remaining_tasks 新增终止或扩容分支。

#### Scenario: 仍有大量剩余任务时优先扩容
- **WHEN** 墙钟到期且 remaining_tasks 显著非零且扩容预算未耗尽
- **THEN** 按既有矩阵优先扩容而非击杀（零事件停滞判停与 absolute_max 封顶仍优先于剩余任务数），evidence 记录剩余任务数

#### Scenario: 扩容预算耗尽
- **WHEN** 扩容次数用满且剩余任务仍非零
- **THEN** 击杀，reason 保持「extension budget exhausted」子串（budget.py:340 豁免判据依赖），evidence 附 remaining_tasks

### Requirement: 击杀用量缺失显式化
击杀类终止 SHALL 在 run 档案落「用量缺失注记」：标明 token/cost 不可得及原因，并记录 transcript 规模类粗估维度，不得静默留空。

#### Scenario: 击杀 run 的用量注记
- **WHEN** run 被墙钟击杀且无 CLI result 事件
- **THEN** run_metrics 附用量缺失注记（原因=provider 无逐轮上报，附 transcript 字节数/轮数粗估维度），成功路径落盘行为不变