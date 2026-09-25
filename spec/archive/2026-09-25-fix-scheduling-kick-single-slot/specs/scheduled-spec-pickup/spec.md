## MODIFIED Requirements

### Requirement: 定时门控为实时评估而非一次性

`start_after` 门控 MUST 为实时评估：SPEC 在未到期期间被晋升/评审入口跳过不产生任何持久化
副作用；当 `start_after` 到期、被清空（置 null）或经手工激活清除哨兵后，该 SPEC MUST 在下一次
评估中经既有晋升/评审链正常推进。

到期后的推进 MUST 复用既有放行侧通道——60 秒粒度的 `check_scheduling_deadlines`
（`drafted` → 晋升链）与清空/激活时的即时唤醒信号（载体形态、写入语义与消费语义见
`scheduling-kick-signal` 能力；本 Requirement MUST NOT 硬编码其文件路径）。
`_recover_ready` 对未到期 SPEC 不重触发派发，故**不构成到期接力路径**。

**唤醒信号成功写出时**，「到期 → 晋升/派发」的延迟上界为秒级（daemon 主循环轮询粒度）。
**唤醒信号写出失败时**，该 SPEC MUST 退回周期扫描兜底——延迟上界为一个扫描周期
（`schedule.poll_interval_minutes`，缺省 30 分钟）。该退化路径 MUST NOT 被静默吞掉：
写入失败 MUST 经 `scheduling-kick-signal` 能力的回报契约告知调用方与用户，且
MUST NOT 被表述为「即时派发」。

#### Scenario: 到期后正常晋升

- **WHEN** 一个此前被跳过的 `drafted` SPEC 的 `start_after` 到期（或置为 null）
- **THEN** 该 SPEC 在下一次 60s 定时到期检测（或扫描）中被晋升，无残留限制；延迟不超过一个检测周期

#### Scenario: 信号成功时秒级派发

- **WHEN** 用户清空某 SPEC 的 `start_after` 且唤醒信号成功落盘
- **THEN** daemon 在该信号被消费的同轮内唤起该 SPEC，延迟为秒级（主循环轮询粒度）

#### Scenario: 信号失败时退回扫描兜底且不宣称即时

- **WHEN** 用户清空某 SPEC 的 `start_after` 但唤醒信号写入失败
- **THEN** 该 SPEC 仍在后续周期扫描中被正常推进，且调用方收到「即时唤醒未生效、将由扫描派发」的明确告知

#### Scenario: 手工激活后正常晋升

- **WHEN** 一个 `start_after` 为 `manual` 的 `drafted` SPEC 被手工激活（哨兵清除为 null）
- **THEN** 该 SPEC 在下一次评估中被晋升，无残留限制
