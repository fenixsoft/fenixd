# SPEC 定时解冻（frozen_until）
<!-- knowledge: capability=scheduled-spec-unfreeze rev=1
     sources=spec/archive/2026-09-12-add-spec-scheduling-controls -->

冻结的 SPEC 可携带解冻时间点自动恢复原状态：`frozen_until` 到期即解冻，永久与定时两种冻结模式可随时互切。

## 规则

- 冻结态 SPEC（status=blocked 且 error 以「用户指令冻结：」前缀开头）在 spec 列表行操作菜单提供「冻结管理」弹窗：展示当前冻结模式（永久冻结，或定时解冻及其目标时间——本地时区渲染）与冻结原因（error 内容）；提供操作：保持永久冻结（清除 `frozen_until`）、设置定时解冻时间（本地时区输入转 ISO8601 UTC 写入 `frozen_until`）、立即解冻（复用既有解冻）。既有「冻结/解冻 Spec」菜单项行为不变。
- `frozen_until` 契约：ISO8601 UTC 时间戳或 null（null 即永久冻结）；仅允许存在于冻结态 SPEC；设置时校验格式，非法格式拒绝写入；已冻结 SPEC 可随时修改（改时间、切永久、切定时）；非冻结态 SPEC 上的残留字段被忽略或清除，不影响调度。
- 到期自动解冻：当前 UTC 时间到达或超过 `frozen_until` 时，恢复从冻结 error 中解析的「原状态」，清空 error 与 `frozen_until`，以既有 status+error 更新模式写回（时间轴可见）。
- 触发双通道：到期定时器精确触发，周期扫描兜底；定时器与扫描竞争时解冻幂等（仅成功执行一次——恢复后 `frozen_until` 已清空，后到者视为无需操作，无重复状态翻转）。
- daemon 重启后内存定时器丢失，周期扫描仍检测到重启期间到期的冻结 SPEC 并执行自动解冻，行为与重启前一致。
- 对冻结 SPEC 设置早于或等于当前时间的 `frozen_until` 时立即执行解冻（等价到期），不等待下一轮定时或扫描，字段不残留。
- 自动解冻在运维记录/时间轴可见且与人工解冻可区分：事件内容含「定时解冻」来源标记；状态变更仍走既有 status+error 更新模式保持时间轴重建兼容。

## 溯源

- 2026-09-12 2026-09-12-add-spec-scheduling-controls — 新增定时解冻：冻结管理弹窗、frozen_until 字段契约、到期自动解冻与幂等、重启扫描兜底、过去时间立即解冻、时间轴来源标记
