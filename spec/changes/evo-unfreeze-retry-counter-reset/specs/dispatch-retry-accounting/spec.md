# dispatch-retry-accounting Specification

## ADDED Requirements

### Requirement: 解冻复位调度重试计数

unfreeze_spec 与 dashboard 管理复位在清零既有计数键集时 MUST 一并清零调度重试计数 _retry_count，解冻后的首轮失败计数 MUST 从 1 起算；MUST NOT 解冻后保留旧计数导致首轮失败即按 N+1/max 越限再冻结。

#### Scenario: 解冻后首轮失败从 1 起算

- **WHEN** spec 按 3/3 冻结后被解冻，随后首轮派发失败
- **THEN** _retry_count 递增为 1/3，不触发冻结；连续失败至第 3 次才按 3/3 冻结

#### Scenario: 管理复位键集合覆盖重试计数

- **WHEN** dashboard 管理复位执行计数清零
- **THEN** 清零集包含 _retry_count 且置 0

### Requirement: 冻结陈述取真实计数

冻结转人工的 error 文案中的已试次数 MUST 取自真实计数器值，MUST NOT 硬编码为上限值（如恒显 3/3）；文案与同事件 ERROR 日志的计数 MUST 一致。

#### Scenario: 越限冻结文案如实呈现

- **WHEN** 计数为 4 时触发冻结
- **THEN** 冻结文案显示 4/3 形态的真实计数，与日志行一致

### Requirement: 人工重推记账显式与信号去重

人工重推计入 push 重试计数时 MUST 标注来源（人工），自动重试上限语义 MUST 保持不变；计数达上限后的重复 push_failed 信号 MUST 去重，MUST NOT 重复触发 daemon_errors 升级链。

#### Scenario: 人工重推达上限后信号去重

- **WHEN** push 重试计数已达上限，人工重推再次失败
- **THEN** 计数如实递增并标注人工来源，但不产生重复的 push_failed 告警/升级信号