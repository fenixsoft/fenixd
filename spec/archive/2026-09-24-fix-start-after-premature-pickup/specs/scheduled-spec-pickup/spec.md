## MODIFIED Requirements

### Requirement: 调度器对未到期 SPEC 跳过拾取

所有**自动**推进 SPEC 进入调度的入口 MUST 在评估某 spec 是否可推进时检查 `start_after`：
若 `start_after` 晚于当前 UTC 时间或为哨兵值 `manual`，MUST 跳过该 spec（仅记 debug
日志），且 MUST NOT 因此写 error 字段或翻转状态（spec 保持原 status）。检查语义与既有
`_dispatch_backoff_until` 退避门控一致。人工显式放行入口（CLI promote/review、Dashboard
晋升/重新评审）不受本 Requirement 约束——见「人工放行不受定时门拦截」Requirement。

该门控的覆盖范围 MUST 包含以下全部入口，MUST NOT 只覆盖 ready 派发口：

- **派发候选筛选**：`ready` 态 spec 的 `_on_spec_ready` 及其它直入派发队列的路径；
- **晋升入口**：`drafted` 态 spec 的晋升链（`_on_spec_drafted`，含 drafted→ready/reviewing
  的全部后代派发）；
- **评审入口**：`reviewing` 态 spec 的评审派发（`_on_spec_reviewing`）。

门控 MUST 施加在 handler 入口且在 handler 内**重读** STATE 取当前 entry（MUST NOT 依赖
调用方传入的 entry 快照）；entry 读不到（SPEC 已删除/归档）时 MUST NOT 早退，交由既有链
自然处理。经上述 handler 进入的**全部自动通道**均受同一门约束——扫描（`_dispatch_changes`）、
恢复（`_recover_one`）、以及框架内部**经 handler 入口**直调的通道（`engine.py:392` 的
`_on_spec_drafted` → `_on_spec_reviewing`）。该覆盖面的边界 MUST 如实表述为「以 handler
入口为界」：**绕过 `_on_spec_reviewing` 直接调用 `SpecReviewManager.dispatch_review`
的通道不在门控范围内**（见「定时门覆盖经 handler 入口的内部直调通道」Requirement）。
**人工显式放行路径不在此列**，见「人工放行不受定时门拦截」Requirement。

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

`start_after` 门控 MUST 只约束**自动**推进通道（扫描、恢复、周期到期检测、框架内部直调）。
人工显式放行操作——CLI `fenix_cli.py promote`、Dashboard「晋升」入口
（`admin_actions.promote_spec`）、CLI `fenix_cli.py review` / Dashboard「重新评审」入口
（`SpecReviewManager.re_review`）——MUST 对其 `start_after` 未到期的 SPEC 继续放行，
MUST NOT 被定时门拒绝或静默跳过。即门控 MUST NOT 下沉到共享晋升函数 `promote_drafted`
（人工通道与自动通道同经此函数），MUST 只落在自动 handler（`_on_spec_drafted` /
`_on_spec_reviewing`）入口。

#### Scenario: 人工晋升未到期的草稿

- **WHEN** 用户对 `drafted` 且 `start_after` 为未来时间的 SPEC 执行人工晋升
- **THEN** 该 SPEC 正常晋升（按评审判定分流到 ready 或 reviewing），定时门不拦截

#### Scenario: 自动路径与人工路径判定可区分

- **WHEN** 同一个 `drafted + 未来 start_after` SPEC 分别经自动扫描与人工晋升处理
- **THEN** 自动路径跳过（保持 drafted），人工路径放行（晋升），二者结论不同且各自符合语义

### Requirement: 定时门覆盖经 handler 入口的内部直调通道

框架内部**经 handler 入口**发起、而非经扫描/恢复事件的自动通道（`engine.py:392`
`_on_spec_drafted` → `_on_spec_reviewing` 的同步直调）MUST 同样受 `start_after` 门约束：
它们进入的是同一自动 handler，未到期/哨兵 SPEC MUST 被跳过，MUST NOT 因此新增第二次
判定或给 handler 增加「调用来源」参数。

**本门控的覆盖面以 handler 入口为界**（与 design D1 末条一致）：`SpecReviewManager.
dispatch_review` 被**绕过 handler 直接调用**的两处——`core/pm_engine/spec_review.py:358`
（评审否决后的自动复评）与 `:845`（人工 `re_review`）——**不在本门控范围内**。堵住该通道
需在 `dispatch_review` 侧加门或加调用来源判据，属独立决策，本 SPEC MUST NOT 声称已覆盖；
未经 `_on_spec_reviewing` 的 `dispatch_review` 直调 MUST NOT 被本门控拦截
（否则人工重评会被定时门误伤）。

#### Scenario: handler 入口的内部直调不绕门

- **WHEN** 某 `drafted`/`reviewing` SPEC 的 `start_after` 为未来时间，框架内部经
  `_on_spec_drafted` → `_on_spec_reviewing` 直调同一 handler
- **THEN** 该 SPEC 被跳过（保持原 status），与扫描/恢复通道结论一致

#### Scenario: 绕过 handler 的直调不受本门约束

- **WHEN** 评审否决后自动复评（`spec_review.py:358`）或人工重评（`spec_review.py:845`）
  直接调用 `dispatch_review`
- **THEN** 不被 `start_after` 门拦截（本 SPEC 有意不覆盖该通道；该边界在 design D1 末条
  与 tasks 3.10 登记，供后续 SPEC 独立治理）

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

到期后的推进 MUST 复用既有放行侧通道——60 秒粒度的 `check_scheduling_deadlines`
（`drafted` → 晋升链）与清空/激活时的 kick 信号（`.fenix/scheduling_kick_request.json`）。
`_recover_ready` 对未到期 SPEC 不重触发派发，故**不构成到期接力路径**；因此
「到期 → 晋升/派发」的延迟上界为 **≤ 一个 60s 检测周期**（外加扫描间隔兜底），
该语义 MUST NOT 被表述为「即时」。

#### Scenario: 到期后正常晋升

- **WHEN** 一个此前被跳过的 `drafted` SPEC 的 `start_after` 到期（或置为 null）
- **THEN** 该 SPEC 在下一次 60s 定时到期检测（或扫描）中被晋升，无残留限制；延迟不超过一个检测周期

#### Scenario: 手工激活后正常晋升

- **WHEN** 一个 `start_after` 为 `manual` 的 `drafted` SPEC 被手工激活（哨兵清除为 null）
- **THEN** 该 SPEC 在下一次评估中被晋升，无残留限制
