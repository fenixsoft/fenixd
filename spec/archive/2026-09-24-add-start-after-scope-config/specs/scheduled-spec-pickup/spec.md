## MODIFIED Requirements

### Requirement: 调度器对未到期 SPEC 跳过拾取

所有**自动**推进 SPEC 进入调度的入口 MUST 在评估某 spec 是否可推进时检查 `start_after`：
若 `start_after` 晚于当前 UTC 时间或为哨兵值 `manual`，MUST 跳过该 spec（仅记 debug
日志），且 MUST NOT 因此写 error 字段或翻转状态（spec 保持原 status）。检查语义与既有
`_dispatch_backoff_until` 退避门控一致。人工显式放行入口（CLI promote/review、Dashboard
晋升/重新评审）不受本 Requirement 约束——见「人工放行不受定时门拦截」Requirement。

该门控的覆盖范围按入口分两类，**实现派发口无条件覆盖**，**晋升/评审入口受配置键
`gates.start_after_scope` 条件覆盖**（见 capability `start-after-scope-config`）：

- **派发候选筛选**（无条件）：`ready` 态 spec 的 `_on_spec_ready` 及其它直入派发队列的
  路径 MUST 始终跳过未到期/哨兵 SPEC，与 scope 取值无关；
- **晋升入口**（受 scope 约束）：`drafted` 态 spec 的晋升链（`_on_spec_drafted`，含
  drafted→ready/reviewing 的全部后代派发）在 `start_after_scope=full` 时 MUST 被跳过；
  在 `dispatch`（缺省）时 MUST 照常晋升；
- **评审入口**（受 scope 约束）：`reviewing` 态 spec 的评审派发（`_on_spec_reviewing`）
  在 `full` 时 MUST 被跳过，在 `dispatch` 时 MUST 照常派发。

门控 MUST 施加在 handler 入口且在 handler 内**重读** STATE 取当前 entry（MUST NOT 依赖
调用方传入的 entry 快照）；entry 读不到（SPEC 已删除/归档）时 MUST NOT 早退，交由既有链
自然处理。经上述 handler 进入的**全部自动通道**均受同一门约束——扫描（`_dispatch_changes`）、
恢复（`_recover_one`）、以及框架内部**经 handler 入口**直调的通道（`engine.py:392` 的
`_on_spec_drafted` → `_on_spec_reviewing`）。该覆盖面的边界 MUST 如实表述为「以 handler
入口为界」：**绕过 `_on_spec_reviewing` 直接调用 `SpecReviewManager.dispatch_review`
的通道不在门控范围内**。**人工显式放行路径不在此列**，见「人工放行不受定时门拦截」
Requirement。

#### Scenario: 未到期不被派发

- **WHEN** spec A 的 `start_after` 为未来时间，daemon 执行派发扫描
- **THEN** spec A 不被派发，其 status 与 error 保持不变，日志记录跳过原因

#### Scenario: 不触发状态自写

- **WHEN** daemon 跳过未到期的 spec A
- **THEN** STATE.md 中 spec A 无任何字段变更（不产生「写 error → 触发 spec_ready 事件」的自触发热循环）

#### Scenario: full 档下未到期的 drafted SPEC 不被晋升

- **WHEN** `gates.start_after_scope` 为 `full`，spec B 处于 `drafted` 且 `start_after` 为未来时间，daemon 执行扫描或恢复
- **THEN** spec B 停留 `drafted` 态（不晋升 ready、不晋升 reviewing、不派发评审 run），日志记录跳过原因

#### Scenario: dispatch 档下未到期的 drafted SPEC 照常晋升

- **WHEN** `gates.start_after_scope` 为 `dispatch`（或缺省），spec B 处于 `drafted` 且 `start_after` 为未来时间，daemon 执行扫描或恢复
- **THEN** spec B 被正常晋升（按评审判定分流 ready/reviewing），仅实现派发等到期

#### Scenario: full 档下未到期的 reviewing SPEC 不派发评审

- **WHEN** `gates.start_after_scope` 为 `full`，spec C 处于 `reviewing` 且 `start_after` 为未来时间，daemon 执行扫描或恢复
- **THEN** spec C 不派发评审 run，状态保持 `reviewing`

#### Scenario: dispatch 档下未到期的 reviewing SPEC 照常派发评审

- **WHEN** `gates.start_after_scope` 为 `dispatch`（或缺省），spec C 处于 `reviewing` 且 `start_after` 为未来时间
- **THEN** spec C 照常派发评审 run

#### Scenario: full 档下待激活哨兵 SPEC 稳定停留草稿态

- **WHEN** `gates.start_after_scope` 为 `full`，spec D 的 `start_after` 为哨兵值 `manual` 且处于 `drafted` 态，daemon 执行扫描或启动恢复
- **THEN** spec D 不被晋升出 `drafted`（保持待激活态，等待人工激活），日志记录跳过原因

### Requirement: 恢复与扫描路径统一受 start_after 门约束

daemon 启动恢复（`event_bus` 对 `drafted` / `reviewing` 状态的 re-trigger）与周期全量扫描
（full scan）在触发任何会推进 SPEC 的 handler 之前，MUST 先评估 `start_after`：在
`gates.start_after_scope=full` 时，未到期或 `manual` 哨兵的 SPEC MUST 被跳过，MUST NOT
产生「re-triggering promote」/「re-triggering spec_reviewing」日志；在 `dispatch`
（缺省）时 MUST 照常触发既有恢复/扫描逻辑。

该早退 MUST 与既有 `_recover_ready` 的 `start_after_pending` 早退同源（复用同一谓词、
同一判定口径），MUST NOT 在恢复路径另写一份判据。判定异常时 MUST 按 fail-open（不早退）
处理，避免新闸门吞掉既有恢复能力。

#### Scenario: full 档下启动恢复不提前晋升定时草稿

- **WHEN** `gates.start_after_scope` 为 `full`，daemon 启动，STATE 中存在 `drafted` 且 `start_after` 为未来时间的 SPEC
- **THEN** 该 SPEC 不被恢复路径晋升，日志无「re-triggering promote」记录，状态保持 `drafted`

#### Scenario: full 档下启动恢复不提前派发定时评审

- **WHEN** `gates.start_after_scope` 为 `full`，daemon 启动，STATE 中存在 `reviewing` 且 `start_after` 为未来时间的 SPEC
- **THEN** 该 SPEC 不被恢复路径触发评审，日志无「re-triggering spec_reviewing」记录

#### Scenario: dispatch 档下恢复照常推进定时草稿

- **WHEN** `gates.start_after_scope` 为 `dispatch`（或缺省），daemon 启动，STATE 中存在 `drafted` 且 `start_after` 为未来时间的 SPEC
- **THEN** 该 SPEC 经恢复路径正常晋升（行为等同于该 SPEC 从未设置 `start_after`）

#### Scenario: 已到期 SPEC 正常放行

- **WHEN** daemon 启动或扫描时，某 `drafted`/`reviewing` SPEC 的 `start_after` 已早于或等于当前时刻
- **THEN** 该 SPEC 经既有晋升/评审链正常推进，行为与从未设置 `start_after` 的 SPEC 完全一致（与 scope 取值无关）

#### Scenario: 判定异常 fail-open 不阻塞恢复

- **WHEN** `start_after` 门控判定过程抛出异常
- **THEN** 恢复路径按「不早退」继续执行既有恢复逻辑，并记录日志
