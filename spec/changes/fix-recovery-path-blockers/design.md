## Context

Fenix 恢复路径的活性判定集中在两处：

- **驱动判定**：`core/admin_monitor.py` 的 `spec_is_undriven`（四条件）是 `event_bus._recover_testing` 与 `admin_monitor._detect_orphaned_state` 共用的单一口径。条件 ① 由模块级 `_has_recent_spec_run` 给出，它对该 SPEC 的**任意 run 前缀**（经 `AdminMonitor._spec_from_run_id` 归一，`RUN_ID_AGENT_PREFIXES` 含 `admin-`）判「近期有写活动」。
- **验证推进**：testing 态的唯一运行时驱动是 `event_bus._recover_testing`（30 分钟 full_scan 内），`_recover_testing` 每次先过 `spec_is_undriven`。

事故链条（2026-09-18 `add-spec-manual-activation`，见 proposal §Why）：预算耗尽停 testing → 15 分钟阈值成 orphaned_state 信号 → admin 处置 75 分钟，其 run 文件使条件 ① 恒假 → 期间恢复判定全跳过 → admin 结束后框架走 `_reset_orphaned_after_disposition` 复位重验，23/23 全绿并 pushed。

既有相邻机制（本设计须与之划清边界）：

- `_dispatch_backoff_until` + `threading.Timer` 重入 `_on_spec_ready`：用于「派发锁冲突 / 秒挂 / 信号死法」三类冷却（`core/pm_engine/dispatch/backoff.py`），到期重入的是 **ready 派发**，不是 testing 重验。
- `check_recovery_watch`（`core/pm_engine/recovery.py`）：恢复后闭环复查，非排程重验。
- `evo-scenario-defect-reroute-stoploss`（在研）：处理「改道无效仍继续消耗改道预算」，判据是**失败集比对**；本 SPEC 处理「预算耗尽无日程」，判据是**耗尽计数**。二者作用于同一函数族的不同分支，不重叠。
- `_SCENARIO_REPAIR_MAX_ROUNDS` 本轮已由独立提交改为 3（`73af41fc`）——数值改动不属本 SPEC，本 SPEC 只补「耗尽后怎么办」。

## Goals / Non-Goals

**Goals:**

1. 让「仅 admin 处置活动」不再被当作被处置 SPEC 的驱动证据，恢复判定回归「真无驱动」语义。
2. 让 verifier 重验派发与在飞 admin run 互斥，避免 admin 写产物（`test_scenarios.json` / STATE）与 verifier 读产物的竞态。
3. 让场景原地修复预算耗尽的 SPEC 获得**显式、可观测、有明确时刻**的重验机会；连续两次耗尽才升级人工。
4. 新增计数与既有 `_judge_rerun_count` 同生命周期，收口「毒 SPEC 借重验日程无限循环」敞口。

**Non-Goals:**

- 不改 `_SCENARIO_REPAIR_MAX_ROUNDS` 数值。
- 不修「full_scan 被阻塞式派发占住」（独立缺口，见 Risks 登记）。
- 不减少「真收敛失败」时升级人工的次数。
- 不改前端 / 不新增 Dashboard 配置键。

## Decisions

### D1：缺口 A 采用「排除 admin 前缀」而非「加 admin 占用超时」

**选择**：在 `_has_recent_spec_run` 与 `AdminMonitor._has_recent_progress` 两处同源实现中排除 `admin-` 前缀（判定口径变为「存在非 admin 前缀的近期 run 文件」）。

**理由**：语义上 admin run 本就不是被处置 SPEC 的驱动。用「排除前缀」是**语义修正**，判定结果与「无 admin 这个前缀」的旧世界逐位一致，对「spec 真有 verifier/implementer 在跑」的样例零影响。相较之下「admin 占用超过 X 分钟才算无驱动」引入了新超时语义与新的阈值配置面，且长跑 admin（本例 75 分钟、233 轮）本身正常。

**替代方案**：

- (a) 给 `admin-` 单独设宽限窗（如 5 分钟）→ 仍需新阈值，且 admin run 停止写盘后仍会挡住判定。
- (b) 在 `spec_is_undriven` 层加 `pm_engine` 查询「是否有在飞 admin run」→ 与 (D1 选型) 叠加才完整（见 D2），单独用则漏掉 `_has_recent_spec_run` 的其他调用点。

**实现约束**：两处实现 MUST 共用同一排除逻辑（模块级函数供 `AdminMonitor` 方法委托），避免二次漂移。

### D2：缺口 A 的并发守卫放在**派发点**而非**判定点**

**选择**：`spec_is_undriven` 保持纯判定（不查 admin 在飞）；在 `event_bus._recover_testing` 与 `admin_monitor` 孤儿复位**派发 verifier 之前**查一次「是否有在飞 admin run」，有则跳过。

**理由**：判定点的语义是「有没有驱动」。admin 在飞**确实是**一种「有人正在管这个 SPEC」的状态——只是不该由 run 文件推断。把它作为**独立的派发前置门**表达，比塞进 `spec_is_undriven` 更清晰：判定函数保持无副作用、无 `pm_engine` 依赖（现有签名已可选注入 `pm_engine`，但那是为条件 ④「无排队派发条目」，语义不同）。

**替代方案**：

- (a) 把 admin 在飞并入 `spec_is_undriven` 条件 ④（「无排队派发」）→ 语义错位：admin run 不在派发队列里。
- (b) 不加守卫，只靠 D1 → 复活「admin 正在改 `test_scenarios.json` 时 verifier 起跑读半成品」的竞态（admin prompt 明确授权它修场景文件，实证确实改了 4 处选择器）。

**守卫实现**：复用既有 `AdminMonitor._has_active_admin_run_for(spec, signal_type, exclude_run_id=None)`（口径：同 `(spec, signal_type)` 存在 `has_pending` 且无终结兄弟记录）的 by_run 归并逻辑，去掉 signal_type 过滤。`event_bus` 与 `admin_monitor` 两处**都**需要该判定时，经下方「取用面」给出的引用取得；不可用时 fail-open 放行并记 WARNING。

**风险点**：admin run 的 `signal_type` 可能是 `orphaned_state` 之外的（如 `verify_env_blocked`、`manual-intervention`、`stuck`）。守卫 MUST 覆盖该 SPEC 的**任意** signal_type——按 `(spec, signal_type)` 精确匹配会漏。故新增 `_has_active_admin_run_for_spec(spec)`（不带 signal_type）并在守卫处使用；既有带 signal_type 的版本保持不动（其调用点语义不同）。

**取用面（实现约束，勿踩空）**：`PMEngine.__init__`（`core/pm_engine/engine.py:247-298`）**不持有** `admin_monitor` 引用——生产装配顺序是 PMEngine 先于 AdminMonitor 构造（`fenixd.py:273` → `:284`），AdminMonitor 拿到 `pm_engine=self.pm_engine`（`fenixd.py:291`），反向无赋值（全仓 `grep pm_engine.admin_monitor` 零命中，仅 `fenixd.py:179` 的 daemon 自持）。`PipelineContext`（`core/pm_engine/verification/context.py:30`）亦只由 pm 单向构造，无 admin 成员。**但 `EventBus` 侧无需新增任何注入**：其入参 `state_machine` 与 `agent_runner`（经 `pm_engine.agent_runner`）两样都可达，而两样各自承载一份「该 SPEC 是否有 admin 处置」的真相：

1. **AdminStore 侧（与 `_has_active_admin_run_for` 同源、无新耦合）**：`AdminStore(project_root, logger)` 是**纯路径构造**的存储层（`core/admin_store.py:49-61`，无 AdminMonitor 依赖），任意位置可 `AdminStore(pm_engine.project_root, logger).read_all()` 后套用同一 by_run 归并。并发安全已核：读路径 `read_all → _read_locked` 每次都重新 `open` 锁文件并取 `LOCK_EX`（`admin_store.py:127-134`、`_lock` 见 `:65-67`），写路径亦为 `LOCK_EX`（`:177-178`）——不存在 SH→EX 升级死锁，读端独立调用安全。
2. **进程表侧（口径互补）**：`agent_runner.running_run_ids()`（`core/agent_runner/runner.py:4320`）只覆盖 `_running_agents` 内有活进程的 run（`runner.py:3372` 注册）——admin run 经 `_run_claude` 派发，**在表内**；故该侧为真 ⟺ 存在**进程存活**的 admin run。与第 1 条互补：第 1 条含「pending 但进程已死」的残骸，第 2 条不含。

   实现取向：守卫取二者**并集**（任一成立即跳过），异常 fail-open。MUST NOT 以「`pm_engine` 无 `admin_monitor` 属性」为由把守卫降级为恒空操作——那会使 D2 整体落空、D1 的并发副作用全量暴露（见 D2b）。

### D2b：同一在飞判定同时抑制「重复唤起 Administrator」（缺此则 D1 引入新并发）

**选择**：`AdminMonitor._handle_signal` 在 `_invoke_administrator` 之前，用 D2 的同一在飞判定（不带 signal_type）检查该 SPEC 是否已有在飞 admin run；有则跳过本次唤起并记 INFO/WARNING，信号仍按既有沉淀/节流语义落 store。

**理由（实测缺口）**：`_has_active_admin_run_for` 在全仓**只有一处**调用——`_recover_orphaned_dispositions` 的孤儿处置重派判重（`core/admin_monitor.py:1819`）。唤起路径（`_handle_signal` → `_invoke_administrator`）**没有任何在飞去重**：唯一的抑制是 `_throttled`（`latest_signal` 冷却窗 + `unhandled_for` 未闭环告警），而冷却窗缺省 `escalation_cooldown_minutes=60`（`core/config.py:1051`），远短于真实 admin 处置时长（本例 75 分钟、233 轮）。D1 生效后，「仅 admin run → 判无驱动」使处置中的 SPEC 在冷却过期后**重新成条**，于是会有第二个 Administrator run 与在飞处置并行写同一批产物——正是 D2 要防的竞态，但 D2 只挡 verifier 侧。本 Decision 把守卫补到唤起侧，使 D1 的副作用（Risk 1）从「噪音告警」收敛为「静默跳过」。

**替代方案**：(a) 拉长 `escalation_cooldown_minutes` → 全局改配置语义，波及所有信号族的告警时效，且长跑 admin 时长无上界，拉多长都可能被超过；(b) 只靠 D2 → 挡不住 admin 自身的并发写（两个 admin 同时改 `test_scenarios.json` / STATE），且第二个 admin 处置的是同一信号的陈旧快照。

**生命周期不对称（有意，须在实现期注意）**：`_has_active_admin_run_for_spec` 依赖「pending 且无终结兄弟记录」，而 run 被 kill（daemon 重启）时 pending 记录会滞留为残骸，需由 `_recover_orphaned_dispositions` 的兜底升级（`admin_reschedule_max` 次重派后转人工）终结（`core/admin_monitor.py:1819-1855` 的 superseded/escalated 落盘）。因此残骸期间本守卫会**持续抑制新唤起**，最长到兜底升级落盘为止。这与 D2 的 verifier 侧守卫风险同源（见 Risks），处置一致：兜底升级通道是既有机制，本 SPEC 不改其阈值。

### D3：缺口 B 的重验日程 = `threading.Timer` 排程 + `_dispatch_backoff_until` 兜底

**选择**：首次耗尽时同时落两样：

1. **排程定时器**：仿 `_schedule_instant_fail_recovery` 的 `threading.Timer` 模式，到期回调重入 `_recover_testing` 等价路径（`spec_implemented` → 入队 verifier + `_process_queue`）。
2. **`_dispatch_backoff_until` 兜底**：写一个相同 deadline，使 `spec_is_undriven` 条件 ③（`Dispatcher._dispatch_backoffed`）在该窗口内为真——避免「15 分钟 orphaned_state 阈值先于排程到期触发」，把「有意等待」结构化表达给探测器（正是条件 ③「start_after 未到期 / 退避未到期」的设计用途）。

**理由**：单靠定时器不够——孤儿探测只看结构化字段，会在 15 分钟时成条（本例正是如此）。单靠 `_dispatch_backoff_until` 不够——它只挡**派发**，「到期后谁来触发」需要 daemon 侧兜底。两者叠加：窗口内探测器静默，到期由定时器（主）+ 周期扫描（兜底）触发重验。

**兜底的真实落点（勿误引）**：兜底**不是** `check_scheduling_deadlines`——该方法只覆盖 `frozen_until` 到期解冻与 `start_after` 到期的 **drafted/ready** 拾取（`core/pm_engine/engine.py:596-700`，`status not in (DRAFTED, READY)` 直接 `continue`），testing 态不在其覆盖范围，这正是下方替代方案 (a) 被否的理由。兜底 = `event_bus._recover_testing` 的周期扫描（`schedule.poll_interval_minutes` 缺省 30 分钟，`core/config.py:358` / `core/event_bus.py:63`）。testing 态**没有** 60 秒精触发通道：`recover_orphan_ready` 对非 ready 直接跳过（`core/event_bus.py:381`），daemon 主循环每 60 秒只调 `recover_orphan_ready`（`fenixd.py:600` 附近）。**由此推论**：兜底的**最坏**延迟是「最长一个扫描周期」，而非「一分钟内」，且定时器与兜底可能同时到期——幂等责任见 D6。

**日程时长**：缺省取 **30 分钟**（与 `poll_interval_minutes` 对齐，确保周期扫描兜底恰好可在同一窗口内接管）；走既有 `agents.*` 命名加可配置键 `agents.scenario_repair_retry_delay_minutes`（缺省 30，合法范围 5–180）。**不新增 Dashboard 界面**——该键属运维调优，非用户交互面；若后续需要在界面暴露，另立 SPEC（对齐「新增配置项必须带 Dashboard 界面」的既有约定，此处按**内部派生常量优先**处理：若实现时判断无需人工调优，可直接用模块常量不入 config）。

**替代方案**：

- (a) 只写 `_dispatch_backoff_until`，靠 `check_scheduling_deadlines` 的 60s 周期触发 → 该函数语义是 ready 态定时拾取，testing 态不在其覆盖范围，需扩语义（改动面更大）。
- (b) 直接升级人工（不排程）→ 用户已否决（「先给一次重验日程，再耗尽才升级人工」）。
- (c) 立即原地重入 → 会绕过 `_SCENARIO_REPAIR_MAX_ROUNDS` 的防护语义，等于无限重入。

### D4：耗尽计数命名与清零点对齐 `_judge_rerun_count`

**选择**：新增 STATE 字段 `_scenario_repair_exhausted_rounds`；清零点 = `verified` 落定（`_record_verdict_adoption` 内既有 `verified` 分支，与 `_judge_rerun_count` 同一处）+ 人工 `unfreeze_spec`。MUST NOT 在 admin 处置复位 / 中间转换清零。

**理由**：与 `_judge_rerun_count` / `_env_block_rounds` 同族——生命周期累计语义，防止「每一轮 admin 复位都重置计数 → 无限循环」。`unfreeze_spec` 清零点对齐 `_env_block_rounds` 既有语义（人工解冻是唯一人工裁决出口）。

**替代方案**：按轮次而非持久计数判定（如比较 `updated` 时间戳）→ 不可靠（admin 处置也会改 `updated`）。

### D5：首次耗尽「保持 testing + 计 error」的表达

**选择**：首次耗尽写 error 文案含明确的下次重验时刻（ISO8601 UTC），形如
`judge 场景原地修复预算耗尽（N 轮）— 已排程重验（<ISO8601>），不再消耗实现预算`；再次耗尽沿用既有「预算耗尽…升级人工」文案。

**实现约束（顺序，勿踩空）**：既有分支先无条件以同一文案覆盖 error（`core/pm_engine/verification/pipeline.py:988-995`）。两态改造 MUST 先读计数并分支出**两条不同文案**再写，MUST NOT 先写旧文案再补写新文案（后者在首次排程路径上会把「下次重验时刻」立刻覆盖掉，Dashboard/CLI 只读 error 字段，Design D5 的可观测目标即落空）。

**理由**：Dashboard / CLI 直读 error 字段；含时刻让运维不必查日志即可判断「该等还是该动」。error 前缀 MUST NOT 命中 `FREEZE_ERROR_PREFIX` / `task-gap` 等既有语义前缀，以免被其他读侧误分类。

### D6：排程与周期兜底可能**同时**触发，幂等由既有队列门承担

**选择**：不假设「定时器管准点、周期扫描管兜底」二者只触发其一。`_dispatch_backoff_until` 到期后，`event_bus._recover_testing` 的下一轮周期扫描会**独立**判定该 testing SPEC 无驱动并派发 verifier；而 30 分钟的 `threading.Timer` 也恰好到期。两条路径都会 `handle_event("spec_implemented", ...)`。

**理由（实测）**：`_recover_testing` 的驱动节律是 `schedule.poll_interval_minutes` 缺省 30 分钟（`core/config.py:358`、`core/event_bus.py:63`），且 daemon 主循环只对 ready 做 60 秒精触发（`fenixd.py` 的 `recover_orphan_ready`，`core/event_bus.py:381` 明确 `status != "ready"` 跳过）——testing **没有**精触发通道。故 D3 选的 30 分钟日程与兜底扫描周期同量级，二者必然同业竞争。

**幂等落点**：`_enqueue` 按 `(spec_name, agent_type)` 去重（`core/pm_engine/dispatch/queue.py:71-73`），且 `_process_queue` 候选筛选处对 `_dispatch_backoffed(spec)` 直接 `continue`（`queue.py:228`、`queue.py:312`）——退避窗内条目不会起 run，到期后只起一次。D3 的排程器 MUST 幂等（同 spec 同耗尽态不排第二个定时器），MUST NOT 新增第二套派发判据。

**替代方案**：(a) 把日程调到远短于 30 分钟（如 5 分钟）→ 与 `orphaned_state_threshold_minutes=15`（`core/admin_monitor.py:107`）的静默关系仍成立，但退避窗内 verifier 条目会长期滞留队列等待，收益不明确；(b) 去掉周期兜底 → daemon 重启后定时器丢失即永久无重验，与 Risk 2 矛盾。

## Risks / Trade-offs

- **[D1 副作用：admin run 不再算驱动 → 正常 admin 处置期间可能触发一次多余的 orphaned_state 信号]** → 由 D2 的派发守卫 + **D2b 的唤起守卫**兜住：信号可成条（无害，admin store 侧按 `(spec, signal_type)` 去重），但既不会导致 verifier 与 admin 并发，也不会产生第二个 Administrator run。若实测噪音明显，后续可在探测器侧也豁免（评估后再动，本 SPEC 保持判定与守卫分离）。
- **[D3 排程定时器在 daemon 重启后丢失]** → `_dispatch_backoff_until` 是持久字段，重启后 `spec_is_undriven` 条件 ③ 仍生效；到期后由 `event_bus._recover_testing` 的**周期扫描**拾取（testing 无精触发通道，最坏延迟 = 一个 `schedule.poll_interval_minutes`）。即「定时器管准点、周期扫描管兜底」。MUST NOT 依赖进程内定时器作为唯一机制。
- **[D3 重验窗口与 orphaned_state 阈值（15 分钟）的关系]** → 日程缺省 30 分钟 > 15 分钟阈值，靠 `_dispatch_backoff_until` 让探测器静默。若运维把日程调短至 < 15 分钟，探测器不会成条（退避窗更短则先到期），无矛盾。
- **[D4 计数不清零导致「一次人工解冻后立刻再次升级」]** → 若首次耗尽已排程、重验仍耗尽 → 计数已为 1 → 升级人工。人工解冻清零后重新获得「一次排程 + 升级」的完整体验，符合设计意图（人工介入 = 重置生命周期）。
- **[独立缺口未覆盖：full_scan 被阻塞式派发占住]**（py-spy 实证 scanner 线程栈停在 `_run_claude` → `run_spec_review` → `_on_spec_reviewing` → `full_scan`）→ 本 SPEC 不修，但 D3 的「显式排程」恰好降低对该周期的依赖。建议后续单独立项（已在 proposal §Non-Goals 登记）。
- **[测试面]**：`spec_is_undriven` / `_has_recent_spec_run` 有既有单测（`tests/test_admin.py`，含 `TestOrphanedRepairProbe.test_active_repair_run_suppresses_undriven`），新增排除逻辑 MUST 补「仅 admin run → 判无驱动」「admin + impl 混合 → 判有驱动」「admin run 过期」三类用例，并保持既有 repair 前缀用例通过。
- **[排除 admin 前缀对 stuck 通道的同向影响（次要，登记不改）]**：`AdminMonitor._has_recent_progress` 同时服务 `_detect_stuck`（`core/admin_monitor.py:1008`，阈值远高于 orphaned）——D1 生效后其「有进度」判据亦不再由 admin run 维持。但 stuck 通道另有「存活 run 进程」反证（`running_ids` + `_spec_from_run_id`，`admin_monitor.py:1063`；admin run 注册在 `_running_agents` 中，见 `core/agent_runner/runner.py:3372`），而 `_has_recent_spec_run` 侧不查进程表，故两通道结论可能不一致。实际影响有限（处置中的 SPEC 通常仍在 testing 短阈值窗口内被 orphaned 通道先接管），且移除 admin 对「被处置 SPEC 有进度」的贡献本就是本 SPEC 的目标方向，故登记不单独修复。
- **[D3 日程与 15 分钟孤立阈值的关系]**：日程缺省 30 分钟 > `orphaned_state_threshold_minutes` 15 分钟（`core/admin_monitor.py:107`），靠 `_dispatch_backoff_until` 让探测器静默。若运维把日程调短至 < 15 分钟，退避窗更短则先到期，探测器不会成条，无矛盾。

## Migration Plan

1. 先落 D1（纯判定修正，风险最低）：两处同源实现各加一层前缀过滤 + 单测。
2. 再落 D2+D2b（守卫）：新增 `_has_active_admin_run_for_spec` + 两个派发点接入 + `_handle_signal` 唤起侧去重 + 单测（在飞/异常 fail-open/无在飞三例）。
3. 最后落 D3+D4（排程与计数）：`_handle_scenario_repaired` 两态分支 + 计数读写 + 清零点（`_record_verdict_adoption` / `unfreeze_spec`）+ 单测（首次排程不升级 / 再次升级 / 重验重获预算 / 两处清零 / admin 复位不清零）。
4. 回滚：三步互相独立，任一步可单独 revert；D3 若需回滚，删除排程与计数即可回到「只写 error」旧行为（`_dispatch_backoff_until` 为通用字段，无害）。

## Open Questions

- `agents.scenario_repair_retry_delay_minutes` 是否需要入 config？倾向**不入**（内部派生常量 30 分钟，与 `poll_interval_minutes` 对齐），除非实现时出现明确的运维调优需求——按「新增配置项必须带 Dashboard 界面」的约定，不入 config 反而更省事。
- 探测器侧是否需要同步豁免（Risk 1）？倾向**本轮不动**，先观察 D2/D2b 守卫是否足够降噪。

## 已核实事实（供实现期直接引用，勿重复取证）

- **事故时间线（`.fenix/logs/fenixd.log`，spec `add-spec-manual-activation`）**：`10:21:11` `judge 场景修复预算耗尽（2 轮）— 不再重入`（当轮 `_SCENARIO_REPAIR_MAX_ROUNDS` 仍为 2，本轮已由 `73af41fc` 改为 3）→ `10:41:10` `orphaned_state` 唤起 Administrator → 该 run 期间无任何恢复动作 → `11:56:15` run 收尾（233 轮）→ `11:56:15` 孤儿复位 `transition_gate(testing)` + verifier 入队 → `12:01:03` 实际派 verifier → `12:02:40` 全绿快道 verified。**「admin 处置全过程无恢复动作」由日志实证成立**。
- **`_recover_testing` 的驱动节律**：仅在 `full_scan`（`schedule.poll_interval_minutes` 缺省 30 分钟，`core/config.py:358`）内；testing **无** 60 秒精触发（`core/event_bus.py:381` 对非 ready 跳过）。
- **清零点覆盖**：`_apply_verified`（`core/pm_engine/verification/pipeline.py:930-931`）与 `unfreeze_spec`（`core/state_machine.py:803`）两处同点即可覆盖 3.3 的全部 verified 落定路径（含 leg 通道 `legacy.py:470`，其内部即调 `_record_verdict_adoption`）；快道 verified 不直调 `_record_verdict_adoption`，实现时勿假设 3.3 的改动会覆盖它。
- **`_dispatch_backoff_until` 的既有写入语义**：`escalation.py:99/147/755/790`、`rollback.py:94/130`、`backoff.py:80` 均写 epoch 秒（`rollback.py:58-68` 的 `float(until) > now.timestamp()` 为消费口径）；**唯一清零**在派发成功后的 `_clear_dispatch_conflict`（`core/pm_engine/recovery.py:554-559`，经 `RecoveryWatch` 派发路径）。3.4 必须用同一口径，且须知：重验**未**经该路径派发时该字段不会被清零，下次同 spec 再次耗尽时旧值已过期、不影响判定。
