## ADDED Requirements

### Requirement: 冻结管理弹窗
spec 列表中处于冻结态的 spec（status=blocked 且 error 以「用户指令冻结：」前缀开头）MUST 在行操作菜单提供「冻结管理」入口，弹出管理弹窗。弹窗 MUST 展示当前冻结模式（永久冻结，或定时解冻及其目标时间——本地时区渲染）与冻结原因，并提供操作：保持永久冻结（清除 `frozen_until`）、设置定时解冻时间（本地时区输入，转 ISO8601 UTC 写入 `frozen_until`）、立即解冻（复用现有解冻）。现有「冻结/解冻 Spec」菜单项行为保持不变。

#### Scenario: 打开弹窗展示当前模式
- **WHEN** 用户对冻结 spec B 打开「冻结管理」弹窗，B 此前为永久冻结
- **THEN** 弹窗显示「永久冻结（人工解冻）」及冻结原因（error 内容）

#### Scenario: 设置定时解冻时间
- **WHEN** 用户在弹窗中选择「定时解冻」并提交时间点 `2026-09-07 09:00`（本地 UTC+8）
- **THEN** STATE.md 中 spec B 的 `frozen_until` 写为 `2026-09-07T01:00:00+00:00` 形式，status/error 保持冻结态不变，弹窗与列表刷新为定时解冻模式

#### Scenario: 切回永久冻结
- **WHEN** 处于定时解冻的 spec B 在弹窗中被切回「永久冻结」
- **THEN** spec B 的 `frozen_until` 被清除（置 null），status/error 保持冻结态

### Requirement: frozen_until 字段契约
`frozen_until` MUST 为 ISO8601 UTC 时间戳或 null（null 即永久冻结）。`frozen_until` 仅允许存在于冻结态 spec 上；设置时 MUST 校验格式，非法格式拒绝写入。已冻结 spec 的 `frozen_until` MUST 允许随时修改（改时间、切永久、切定时）。非冻结态 spec 的 `frozen_until` MUST 被忽略或清除，不影响调度。

#### Scenario: 非法格式拒绝
- **WHEN** 冻结管理请求携带 `frozen_until: "下周一"`
- **THEN** API 返回错误，STATE.md 中该字段不变

#### Scenario: 非冻结态字段被忽略
- **WHEN** spec C 处于 ready 且残留 `frozen_until`（如解冻后异常残留）
- **THEN** spec C 正常参与调度，不受该字段影响

### Requirement: 到期自动解冻
daemon MUST 检测冻结态 spec 的 `frozen_until`：当当前 UTC 时间到达或超过 `frozen_until` 时，MUST 自动执行解冻——恢复从冻结 error 中解析的「原状态 X」，清空 error 与 `frozen_until`，并以既有 status+error 更新模式写回（时间轴可见）。到期解冻 SHOULD 通过到期定时器精确触发，周期扫描 MUST 作为兜底；定时器与扫描竞争时解冻 MUST 为幂等（仅成功执行一次，恢复后 `frozen_until` 已清空，后到者视为无需操作）。

#### Scenario: 到期自动解冻恢复原状态
- **WHEN** 冻结 spec B（原状态 ready）的 `frozen_until` 到达
- **THEN** spec B 的 status 恢复为 ready，error 清空，`frozen_until` 清空，后续正常调度

#### Scenario: 幂等竞争
- **WHEN** 到期定时器与周期扫描同时检测到 spec B 到期
- **THEN** 仅一次解冻生效（status 恢复原状态、字段清空），无重复状态翻转

### Requirement: daemon 重启后兜底解冻
daemon 重启后（内存定时器丢失），周期扫描 MUST 仍能检测到 `frozen_until` 已到期的冻结 spec 并执行自动解冻，行为与重启前一致。

#### Scenario: 重启后扫描兜底
- **WHEN** daemon 重启，存在冻结 spec B 的 `frozen_until` 已在重启期间到期
- **THEN** 重启后的周期扫描中 spec B 被自动解冻并恢复原状态

### Requirement: 设置过去时间立即解冻
当对冻结 spec 设置的 `frozen_until` 早于或等于当前时间时，系统 MUST 立即执行解冻（等价于到期），而非等待下一轮定时或扫描。

#### Scenario: 提交过去时间立即解冻
- **WHEN** 用户对冻结 spec B 设置 `frozen_until` 为已过去的时间
- **THEN** spec B 立即被解冻并恢复原状态，`frozen_until` 不残留

### Requirement: 自动解冻事件可追溯
自动解冻（定时到期触发）MUST 在运维记录/时间轴中可见，且与人工解冻可区分（事件内容含「定时解冻」来源标记）；状态变更仍走既有 status+error 更新模式以保持时间轴重建兼容。

#### Scenario: 时间轴记录自动解冻
- **WHEN** 冻结 spec B 到期被自动解冻
- **THEN** 运维记录/时间轴出现来源为「定时解冻」的状态恢复事件，人工解冻事件不携带该标记
