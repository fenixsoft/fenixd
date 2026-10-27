## ADDED Requirements

### Requirement: 排程重验状态持久化

场景修复预算耗尽等验证链信号的排程重验 MUST 将排程时间戳与来源信号写入 STATE 条目结构化字段（如 `_reverify_scheduled_at`/`_reverify_reason`），MUST NOT 仅存在于 error 文本或进程内存。字段与排程写入在同一原子写内落盘。

#### Scenario: 排程落盘可被恢复路径读取
- **WHEN** 验证链排程一次未来重验
- **THEN** STATE 条目含排程时间戳结构化字段，daemon 重启后新实例可读出该排程

### Requirement: 恢复路径识别排程等待态

daemon 全扫恢复路径对 testing 态的孤儿判定 MUST 前置检查「存在未到期排程重验」：命中时 MUST 保持 testing 态不重置（不写 "Recovered from interrupted state"），保留排程字段；排程到点由周期扫描触发重验（调度消费读 STATE 字段，重启后到点仍执行）。排程已到期但未执行的情形，恢复路径 MUST 直接触发该重验而非重置状态。

#### Scenario: 重启不吞未到期排程
- **WHEN** testing 态存在未到期排程重验字段且 daemon 重启，新实例全扫命中该 spec
- **THEN** spec 保持 testing、排程字段保留，无 "Recovered from interrupted state" 重置，到点重验照常执行

#### Scenario: 到期未执行的重验被恢复拾起
- **WHEN** 排程时间戳已过且重验尚未执行（重启恰发生在排程到期窗口）
- **THEN** 恢复路径触发该重验（进入正常验证周期），不把 testing 态重置为 implemented

#### Scenario: 无排程的孤儿态维持既有恢复
- **WHEN** testing 态无排程字段且无在飞 run（真孤儿态）
- **THEN** 恢复路径维持既有行为（重置 implemented + "Recovered from interrupted state"），行为逐位不变
