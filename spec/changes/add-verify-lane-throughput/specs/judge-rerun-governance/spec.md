# judge-rerun-governance 能力增量（add-verify-lane-throughput）

> judge 重裁决治理契约：同一 spec 同一验证轮内的重裁决（不稳定/失败重派）计数达到阈值即停止派发、转人工升级；低置信判定优先证据扩充；fast-track 复用命中率可观测。

## ADDED Requirements

### Requirement: 重裁决计数与阈值升级

验证管线 MUST 按（spec, 验证轮）维度维护 judge 派发计数：真实派发（非 fast-track 复用命中）每次递增；计数随验证轮重置（bug-found 修复进入新一轮验证时从零计）。当本轮真实派发次数达到 2 且仍需再次派发 judge 时，MUST NOT 发起第 3 次派发，转而：①发送人工升级告警（复用既有 human-escalation-alert 通道，内容含 spec、验证轮、历次 judge 结论摘要）；②spec 保持可重试状态（不冻结、不销毁产物），人工处置后重入 testing 按正常路径执行。

#### Scenario: 连续两次重裁决后停派升级

- **WHEN** 某验证轮内 judge 第 1 次派发结论被判不稳定、第 2 次派发仍不稳定，管线准备第 3 次派发
- **THEN** 第 3 次派发被阻止，发出含两次结论摘要的人工升级告警，spec 状态允许人工触发重试

#### Scenario: 新验证轮计数重置

- **WHEN** 上一验证轮 judge 触达停派阈值后经人工处置，spec 经 bug-found 修复进入新一轮验证
- **THEN** judge 派发计数从 0 重新开始，本轮第 1 次 judge 派发正常执行

### Requirement: 低置信优先证据扩充

judge 产物被判定低置信（缺 evidence、evidence 截断等可补类型）时，管线 MUST 优先触发证据扩充路径（对该判定项补齐证据后局部重判），MUST NOT 直接整轮重派 judge；证据扩充每轮至多 1 次，扩充后仍低置信的按重裁决计数处理。不可补类型（结论冲突、产物损坏）直接按重裁决计数处理。

#### Scenario: 缺证据时扩充而非重派

- **WHEN** judge 结论中某失败判定缺 evidence 且属于可补类型
- **THEN** 管线对该判定项补齐证据并局部重判，本轮 judge 真实派发计数不因该次扩充递增（扩充非重派）

### Requirement: fast-track 命中率可观测

读侧数据层 MUST 在 spec 级 summary 字段中暴露 judge fast-track 复用统计：`judge_fasttrack_hits`（快道复用次数）、`judge_real_dispatches`（真实派发次数）、按验证轮累计。统计来源为既有 fast-track 复用门的判定记录；字段缺失（历史 spec 无记录）时读侧 fail-open 呈现空值，MUST NOT 抛异常。本期不要求前端组件展示。

#### Scenario: 统计字段随验证轮累计

- **WHEN** 某 spec 首轮验证 judge 真实派发 1 次，修复轮 fast-track 命中 1 次
- **THEN** 该 spec summary 输出 `judge_fasttrack_hits: 1`、`judge_real_dispatches: 1`

#### Scenario: 历史 spec 空值兼容

- **WHEN** 读取无任何 judge 记录的历史 spec 的 summary
- **THEN** 统计字段为空值（null 或缺省），解析不抛异常、不影响其他 summary 字段
