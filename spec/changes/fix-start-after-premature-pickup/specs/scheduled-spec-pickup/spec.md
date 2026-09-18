## MODIFIED Requirements

### Requirement: 调度器对未到期 SPEC 跳过拾取

所有会推进 SPEC 进入调度的入口 MUST 在评估某 spec 是否可推进时检查 `start_after`：
若 `start_after` 晚于当前 UTC 时间或为哨兵值 `manual`，MUST 跳过该 spec（仅记 debug
日志），且 MUST NOT 因此写 error 字段或翻转状态（spec 保持原 status）。检查语义与既有
`_dispatch_backoff_until` 退避门控一致。

该门控的覆盖范围 MUST 包含以下全部入口，MUST NOT 只覆盖 ready 派发口：

- **派发候选筛选**：`ready` 态 spec 的 `_on_spec_ready` 及其它直入派发队列的路径；
- **晋升入口**：`drafted` 态 spec 的晋升链（`_on_spec_drafted`，含 drafted→ready/reviewing
  的全部后代派发）；
- **评审入口**：`reviewing` 态 spec 的评审派发（`_on_spec_reviewing`）。

#### Scenario: 未到期不被派发

- **WHEN** spec A 的 `start_after` 为未来时间，daemon 执行派发扫描
- **THEN** spec A 不被派发，其 status 与 error 保持不变，日志记录跳过原因

#### Scenario: 不触发状态自写

- **WHEN** daemon 跳过未到期的 spec A
- **THEN** STATE.md 中 spec A 无任何字段变更（不产生「写 error → 触发 spec_ready 事件」的自触发热循环）

#### Scenario: 未到期的 drafted SPEC 不被晋升

- **WHEN** spec B 处于 `drafted` 且 `start_after` 为未来时间，daemon 执行扫描或恢复
- **THEN** spec B 停留 `drafted` 态（不晋升 ready、不晋升 reviewing、不派发评审 run），日志记录跳过原因

#### Scenario: 未到期的 reviewing SPEC 不派发评审

- **WHEN** spec C 处于 `reviewing` 且 `start_after` 为未来时间，daemon 执行扫描或恢复
- **THEN** spec C 不派发评审 run，状态保持 `reviewing`

#### Scenario: 待激活哨兵 SPEC 稳定停留草稿态

- **WHEN** spec D 的 `start_after` 为哨兵值 `manual` 且处于 `drafted` 态，daemon 执行扫描或启动恢复
- **THEN** spec D 不被晋升出 `drafted`（保持待激活态，等待人工激活），日志记录跳过原因

## ADDED Requirements

### Requirement: 人工放行不受定时门拦截

`start_after` 门控 MUST 只约束**自动**推进通道（扫描、恢复、周期到期检测）。人工显式
放行操作——CLI `fenix_cli.py promote`、Dashboard「晋升」入口（`admin_actions.promote_spec`）
——MUST 对其 `start_after` 未到期的 `drafted` SPEC 继续放行，MUST NOT 被定时门拒绝或静默
跳过。即门控 MUST NOT 下沉到共享晋升函数 `promote_drafted`（人工通道与自动通道同经此
函数），MUST 只落在自动 handler（`_on_spec_drafted` / `_on_spec_reviewing`）入口。

#### Scenario: 人工晋升未到期的草稿

- **WHEN** 用户对 `drafted` 且 `start_after` 为未来时间的 SPEC 执行人工晋升
- **THEN** 该 SPEC 正常晋升（按评审判定分流到 ready 或 reviewing），定时门不拦截

#### Scenario: 自动路径与人工路径判定可区分

- **WHEN** 同一个 `drafted + 未来 start_after` SPEC 分别经自动扫描与人工晋升处理
- **THEN** 自动路径跳过（保持 drafted），人工路径放行（晋升），二者结论不同且各自符合语义

## ADDED Requirements

### Requirement: 恢复与扫描路径统一受 start_after 门约束

daemon 启动恢复（`event_bus` 对 `drafted` / `reviewing` 状态的 re-trigger）与周期全量扫描
（full scan）在触发任何会推进 SPEC 的 handler 之前，MUST 先评估 `start_after`：未到期或
`manual` 哨兵的 SPEC MUST 被跳过，MUST NOT 产生「re-triggering promote」/「re-triggering
spec_reviewing」日志。

该早退 MUST 与既有 `_recover_ready` 的 `start_after_pending` 早退同源（复用同一谓词、
同一判定口径），MUST NOT 在恢复路径另写一份判据。判定异常时 MUST 按 fail-open（不早退）
处理，避免新闸门吞掉既有恢复能力。

#### Scenario: 启动恢复不提前晋升定时草稿

- **WHEN** daemon 启动，STATE 中存在 `drafted` 且 `start_after` 为未来时间的 SPEC
- **THEN** 该 SPEC 不被恢复路径晋升，日志无「re-triggering promote」记录，状态保持 `drafted`

#### Scenario: 启动恢复不提前派发定时评审

- **WHEN** daemon 启动，STATE 中存在 `reviewing` 且 `start_after` 为未来时间的 SPEC
- **THEN** 该 SPEC 不被恢复路径触发评审，日志无「re-triggering spec_reviewing」记录

#### Scenario: 已到期 SPEC 正常放行

- **WHEN** daemon 启动或扫描时，某 `drafted`/`reviewing` SPEC 的 `start_after` 已早于或等于当前时刻
- **THEN** 该 SPEC 经既有晋升/评审链正常推进，行为与从未设置 `start_after` 的 SPEC 完全一致

#### Scenario: 判定异常 fail-open 不阻塞恢复

- **WHEN** `start_after` 门控判定过程抛出异常
- **THEN** 恢复路径按「不早退」继续执行既有恢复逻辑，并记录日志

### Requirement: 定时门控为实时评估而非一次性

`start_after` 门控 MUST 为实时评估：SPEC 在未到期期间被晋升/评审入口跳过不产生任何持久化
副作用；当 `start_after` 到期、被清空（置 null）或经手工激活清除哨兵后，该 SPEC MUST 在下一次
评估中经既有晋升/评审链正常推进。

#### Scenario: 到期后正常晋升

- **WHEN** 一个此前被跳过的 `drafted` SPEC 的 `start_after` 到期（或置为 null）
- **THEN** 该 SPEC 在下一次扫描或 60s 定时到期检测中被晋升，无残留限制

#### Scenario: 手工激活后正常晋升

- **WHEN** 一个 `start_after` 为 `manual` 的 `drafted` SPEC 被手工激活（哨兵清除为 null）
- **THEN** 该 SPEC 在下一次评估中被晋升，无残留限制
