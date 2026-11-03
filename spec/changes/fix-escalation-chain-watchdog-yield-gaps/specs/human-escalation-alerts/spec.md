# human-escalation-alerts Spec

## ADDED Requirements

### Requirement: 孤儿看护升级链痕抑制与归因取证

AdminMonitor 孤儿看护的 pending 超时升级 SHALL 在开火前查链痕：同签名存在链 in_flight 条目、deferred 让行条目、或 arbiter 单飞队列在飞调查任一命中时，MUST NOT 产生升级告警且 MUST NOT 终结 pending disposition（保持原状，待链痕消失后下一轮巡检重判）。链痕全部消失且 pending 仍超时时照常升级，既有「升级即终结 pending」与「run 文件含 interrupted 标记=已知中断终结不告警」口径不变。

孤儿升级告警的 description 归因 SHALL 按 run 文件终态证据生成（如 frozen-terminated 写明冻结击杀、killed 写明击杀来源、无证据保守写「死因不明」），MUST NOT 使用与 run 终态无关的固定归因模板（废弃「疑似 daemon 重启/崩溃连带杀死 admin」一刀切文案）。

#### Scenario: 链在飞抑制重复出件

- **WHEN** pending disposition 超时但同签名 arbiter 调查在飞（或链 in_flight/deferred 留痕在场）
- **THEN** 不产生升级告警、不终结 pending disposition；链终点上升件是该事件的唯一人工作品

#### Scenario: 链痕消失后兜底升级

- **WHEN** 同签名链痕全部被 reap 且 pending disposition 仍超时
- **THEN** 孤儿看护照常升级人工并终结 pending（既有升级形态不变）

#### Scenario: 归因照 run 终态实证写

- **WHEN** 孤儿升级开火且 run 文件终态为 frozen-terminated（0 API 轮次）
- **THEN** 告警归因写明「spec 冻结击杀」证据与时间，不出现「疑似 daemon 重启/崩溃」误导文案

#### Scenario: 死因不明保守兜底

- **WHEN** 孤儿升级开火且 run 文件不存在或无终态证据可查
- **THEN** 归因保守写「死因不明（run 证据缺失）」，升级与终结行为照常（宁多告警不漏告警）

#### Scenario: 已知中断口径不变

- **WHEN** run 文件含 `{"type": "interrupted"}` 标记
- **THEN** 维持既有行为：追加 interrupted 终结记录、不产生告警
