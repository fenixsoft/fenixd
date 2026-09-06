## ADDED Requirements

### Requirement: fenix-new 提交时可指定定时拾取时间
用户通过 `/fenix-new` 创建 SPEC 时，MUST 支持以参数形式指定 `start_after`（在此时间点之后 SPEC 才可被 daemon 拾取）。时间支持两种写法：绝对时间（如 `2026-09-07 09:00`，按本地时区 UTC+8 解释）与相对时长（如 `+2h`、`+30m`，按提交时刻解释）。Agent MUST 将两者统一换算为 ISO8601 UTC 时间戳，经 `StateMachine.add_spec` 注册时写入 STATE.md entry 的 `start_after` 字段。未指定时 `start_after` MUST 为 null（立即进入调度）。

#### Scenario: 绝对时间写入
- **WHEN** 用户执行 `/fenix-new "xxx" --start-after "2026-09-07 09:00"`（本地 UTC+8）
- **THEN** STATE.md 中该 spec entry 的 `start_after` 为对应 UTC 时间戳 `2026-09-07T01:00:00+00:00` 形式

#### Scenario: 相对时长写入
- **WHEN** 用户执行 `/fenix-new "xxx" --start-after +2h`，提交时刻为 UTC `2026-09-06T10:00:00`
- **THEN** STATE.md 中该 spec entry 的 `start_after` 为 `2026-09-06T12:00:00+00:00` 形式

#### Scenario: 未指定时缺省 null
- **WHEN** 用户执行 `/fenix-new "xxx"` 未带定时参数
- **THEN** 该 spec entry 无 `start_after` 字段或其值为 null，daemon 立即按既有逻辑拾取

### Requirement: 调度器对未到期 SPEC 跳过拾取
daemon 派发候选筛选 MUST 在评估某 spec 是否可派发时检查 `start_after`：若 `start_after` 晚于当前 UTC 时间，MUST 跳过该 spec（仅记 debug 日志），且 MUST NOT 因此写 error 字段或翻转状态（spec 保持原 status，如 drafted/ready）。检查语义与既有 `_dispatch_backoff_until` 退避门控一致。

#### Scenario: 未到期不被拾取
- **WHEN** spec A 的 `start_after` 为未来时间，daemon 执行派发扫描
- **THEN** spec A 不被派发，其 status 与 error 保持不变，日志记录跳过原因

#### Scenario: 不触发状态自写
- **WHEN** daemon 跳过未到期的 spec A
- **THEN** STATE.md 中 spec A 无任何字段变更（不产生「写 error → 触发 spec_ready 事件」的自触发热循环）

### Requirement: 到期后自动进入正常调度
`start_after` 门控 MUST 为实时评估：到达 `start_after` 时间点后，该 spec 在下一次派发评估中 MUST 被正常拾取，行为与从未设置过 `start_after` 的 spec 完全一致。daemon SHOULD 通过到期定时器精确触发，且周期扫描（full_scan）MUST 作为兜底路径，二者先后到达均只触发一次正常派发。

#### Scenario: 到期后正常拾取
- **WHEN** 当前 UTC 时间晚于 spec A 的 `start_after`，daemon 执行派发评估
- **THEN** spec A 按既有优先级与依赖规则参与候选，不残留任何定时相关限制

### Requirement: Dashboard 展示定时拾取倒计时并支持修改
spec 列表 MUST 对 `start_after` 未到期的 spec 展示定时拾取标记（含目标时间与倒计时，目标时间以本地时区渲染）。行操作菜单 MUST 提供「设置拾取时间」入口：可将 `start_after` 修改为新的时间点（本地时区输入，转 UTC 存储），也可清除定时（`start_after` 置 null，立即恢复调度）。

#### Scenario: 列表展示等待标记
- **WHEN** spec A 的 `start_after` 为未来时间
- **THEN** 列表中 spec A 行展示定时拾取标记与目标时间、倒计时

#### Scenario: 修改拾取时间
- **WHEN** 用户在 spec A 行菜单选择「设置拾取时间」并提交新时间点
- **THEN** STATE.md 中 spec A 的 `start_after` 更新为新值，列表标记随之刷新

#### Scenario: 清除定时立即恢复调度
- **WHEN** 用户在「设置拾取时间」弹窗中选择清除定时
- **THEN** spec A 的 `start_after` 置 null，该 spec 在下一次派发评估中可被拾取

### Requirement: start_after 字段格式与边界语义
`start_after` MUST 为 ISO8601 UTC 时间戳或 null。写入路径（fenix-new 注册、dashboard 修改）MUST 校验格式，非法格式拒绝写入。`start_after` 早于或等于当前时间的值 MUST 等价于 null（不阻塞拾取）。终态 spec（done/pushed）的 `start_after` 不影响任何行为。

#### Scenario: 非法格式拒绝写入
- **WHEN** 修改请求携带 `start_after: "明天早上"`
- **THEN** API 返回错误，STATE.md 中该字段不变

#### Scenario: 过去时间等价无限制
- **WHEN** spec A 的 `start_after` 被设置为已过去的时间
- **THEN** spec A 在下一次派发评估中被正常拾取
