# fasttrack-branch-anchor 规格

## ADDED Requirements

### Requirement: fast-track 车道锚点提前落盘

fast-track 车道 run 成功产出分支后、执行 merge-back 前，系统 SHALL 在 spec 状态落 `branch` 与 `implementer_run` 锚点（与 full 车道 merge 前写点同契约）；写入失败 SHALL NOT 阻塞 merge-back 主流程。

### Requirement: 阻断等待链按锚点自动接手

fast-track spec 因 WIP 重叠闸门或 spec 目录在飞编辑被阻断等待后，自动接手链（WIP 周期复查消费者、顺延 merge-only 重试链）SHALL 能从 spec 状态读到分支锚点并完成 merge-only 重试，SHALL NOT 因锚点缺失进入 `mergeback_branch_anchor_missing` 告警循环。

### Requirement: 既有机制不变

锚点提前落盘 SHALL NOT 改变：成功收口写点语义（幂等重写同值）、WIP 重叠闸门阻塞与告警语义、spec_dir_inflight 顺延语义、boot 复位清锚点语义、ready 降级重派的既有清锚点时机、full 车道既有锚点写点。

#### Scenario: WIP 阻断后周期消费者自动合回

- WHEN fast-track run 成功且 merge-back 被 WIP 重叠闸门阻塞（wip_gate_blocked=True）
- THEN STATE 已含 branch/implementer_run 锚点；主树重叠改动清理后，周期消费者单拍内完成 merge-only 重试并正常收尾，无锚点缺失告警

#### Scenario: spec_dir_inflight 顺延重试可合并

- WHEN fast-track merge-back 因 spec 目录在飞编辑进入 `_defer_merge_back` 顺延
- THEN 排程的 merge-only 重试按 STATE 锚点执行合并，不再回锚点缺失出口

#### Scenario: full 车道与收口语义不回归

- WHEN full 车道执行成功 run、fast-track 车道执行 merge 成功收口
- THEN 两者既有锚点写点行为不变，fast-track 与 WIP 消费者既有测试全绿
