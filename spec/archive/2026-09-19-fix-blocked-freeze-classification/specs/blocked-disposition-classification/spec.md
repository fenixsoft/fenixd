## ADDED Requirements

### Requirement: blocked 停摆的二分类契约

每次写入 `status=blocked` 时，系统 MUST 将该停摆显式归入下列两类之一，MUST NOT 产生两者皆无的裸 blocked：

- **冻结转人工**（frozen=True）：admin agent 对根因无操作杠杆、需人在场决策的停摆。MUST 在写入 blocked 的同时发送人工升级告警。
- **阻塞待 admin**（不写 frozen）：admin agent 可自动修复（改环境 / 起草契约 / 清 git 状态等）的停摆，由 admin 巡检介入。

#### Scenario: 冻结类必然成对写入 frozen 与告警
- **WHEN** 任一站点将 SPEC 置为「冻结转人工」类 blocked
- **THEN** 该 SPEC 的 `frozen` 字段为真，且同一动作发出人工升级告警
- **AND** 不存在「frozen=True 但无人工告警」的静默冻结

#### Scenario: 阻塞类不写 frozen 以保留 admin 介入
- **WHEN** 站点将 SPEC 置为「阻塞待 admin」类 blocked
- **THEN** `frozen` 字段不写入真值，`admin_monitor` 的超时巡检仍会唤起 Administrator

### Requirement: 评审路径归入冻结转人工

SPEC 评审（spec-review）的否决与「评审尝试耗尽」把 SPEC 置为 blocked 时，MUST 按冻结转人工处理（`frozen=True` + 人工升级告警），MUST NOT 仅置 blocked 却不打冻结标记——否则 admin 巡检会对方案类停摆做无杠杆的重复介入。

#### Scenario: 评审否决触发冻结并告警
- **WHEN** spec-review 裁决为 `rejected`，框架将其置为 blocked
- **THEN** SPEC 写入 `frozen=True` 并发送人工升级告警（含否决 findings 摘要与评审 run id）
- **AND** `admin_monitor` 不再对该 SPEC 发起 blocked_stuck 唤起

#### Scenario: 评审尝试耗尽触发冻结并告警
- **WHEN** 评审 run 连续未通过结果硬门达尝试上限（`spec-review-incomplete`），框架将其置为 blocked
- **THEN** SPEC 写入 `frozen=True` 并发送人工升级告警（含连续失败原因）

### Requirement: 自动冻结不得静默

任何自动路径把 SPEC 冻结为 blocked 时 MUST 同时发出人工升级告警，MUST NOT 出现「打了 frozen 标记但无人被通知」的静默冻结。

#### Scenario: 重启重验超限补告警
- **WHEN** daemon 重启恢复使某 SPEC 的重启重验计数达上限并冻结为 blocked
- **THEN** 该 SPEC 除写 `frozen=True` 外，另发一条人工升级告警（逐 SPEC 触发，不聚合丢失）

### Requirement: blocked 二分类的文档契约

系统 MUST 在生命周期文档中记录 blocked 的二分类语义、判据与各类消费者（admin 豁免 / dashboard 标签 / 人工告警），使新增 blocked 写入点有据可依。

#### Scenario: 文档可据以判定新站点归类
- **WHEN** 维护者新增一个写 `status=blocked` 的站点
- **THEN** 生命周期文档给出「admin 是否有杠杆」的判据与两类各自的强制副作用，可据此决定 frozen 与告警
