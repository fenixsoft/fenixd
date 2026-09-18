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

**守卫实现**：复用既有 `AdminMonitor._has_active_admin_run_for(spec, signal_type, exclude_run_id=None)`（口径：同 `(spec, signal_type)` 存在 `has_pending` 且无终结兄弟记录）。调用点若在 `event_bus`，经注入的 `pm_engine` → `admin_monitor` 引用取用；不可用时 fail-open 放行并记 WARNING。

**风险点**：admin run 的 `signal_type` 可能是 `orphaned_state` 之外的（如 `verify_env_blocked`、`manual-intervention`）。守卫 MUST 覆盖该 SPEC 的**任意** signal_type——按 `(spec, signal_type)` 精确匹配会漏。故新增 `_has_active_admin_run_for_spec(spec)`（不带 signal_type）并在守卫处使用；既有带 signal_type 的版本保持不动（其调用点语义不同）。

### D3：缺口 B 的重验日程 = `threading.Timer` 排程 + `_dispatch_backoff_until` 兜底

**选择**：首次耗尽时同时落两样：

1. **排程定时器**：仿 `_schedule_instant_fail_recovery` 的 `threading.Timer` 模式，到期回调重入 `_recover_testing` 等价路径（`spec_implemented` → 入队 verifier + `_process_queue`）。
2. **`_dispatch_backoff_until` 兜底**：写一个相同 deadline，使 `spec_is_undriven` 条件 ③（`Dispatcher._dispatch_backoffed`）在该窗口内为真——避免「15 分钟 orphaned_state 阈值先于排程到期触发」，把「有意等待」结构化表达给探测器（正是条件 ③「start_after 未到期 / 退避未到期」的设计用途）。

**理由**：单靠定时器不够——孤儿探测只看结构化字段，会在 15 分钟时成条（本例正是如此）。单靠 `_dispatch_backoff_until` 不够——它只挡**派发**，而「到期后谁来触发」需要 daemon 侧兜底（`check_scheduling_deadlines` 每分钟一轮，可复用）。两者叠加：窗口内探测器静默，到期由定时器（主）+ 周期扫描（兜底）触发重验。

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

**理由**：Dashboard / CLI 直读 error 字段；含时刻让运维不必查日志即可判断「该等还是该动」。error 前缀 MUST NOT 命中 `FREEZE_ERROR_PREFIX` / `task-gap` 等既有语义前缀，以免被其他读侧误分类。

## Risks / Trade-offs

- **[D1 副作用：admin run 不再算驱动 → 正常 admin 处置期间可能触发一次多余的 orphaned_state 信号]** → 由 D2 的派发守卫兜住：信号可成条（无害，admin store 侧按 `(spec, signal_type)` 去重且 `_has_active_admin_run_for` 使重复唤起被挡），但**不会**导致 verifier 与 admin 并发。若实测噪音明显，后续可在探测器侧也豁免（评估后再动，本 SPEC 保持判定与守卫分离）。
- **[D3 排程定时器在 daemon 重启后丢失]** → `_dispatch_backoff_until` 是持久字段，重启后 `spec_is_undriven` 条件 ③ 仍生效；到期后由 `event_bus` full_scan / `recover_orphan_ready` 等价路径拾取。即「定时器管准点、周期扫描管兜底」。MUST NOT 依赖进程内定时器作为唯一机制。
- **[D3 重验窗口与 orphaned_state 阈值（15 分钟）的关系]** → 日程缺省 30 分钟 > 15 分钟阈值，靠 `_dispatch_backoff_until` 让探测器静默。若运维把日程调短至 < 15 分钟，探测器不会成条（退避窗更短则先到期），无矛盾。
- **[D4 计数不清零导致「一次人工解冻后立刻再次升级」]** → 若首次耗尽已排程、重验仍耗尽 → 计数已为 1 → 升级人工。人工解冻清零后重新获得「一次排程 + 升级」的完整体验，符合设计意图（人工介入 = 重置生命周期）。
- **[独立缺口未覆盖：full_scan 被阻塞式派发占住]**（py-spy 实证 scanner 线程栈停在 `_run_claude` → `run_spec_review` → `_on_spec_reviewing` → `full_scan`）→ 本 SPEC 不修，但 D3 的「显式排程」恰好降低对该周期的依赖。建议后续单独立项（已在 proposal §Non-Goals 登记）。
- **[测试面]**：`spec_is_undriven` / `_has_recent_spec_run` 有既有单测（`tests/test_admin.py`），新增排除逻辑 MUST 补「仅 admin run → 判无驱动」「admin + impl 混合 → 判有驱动」两类用例，并保持既有 repair 前缀用例（`tests/test_admin.py:804`）通过。

## Migration Plan

1. 先落 D1（纯判定修正，风险最低）：两处同源实现各加一层前缀过滤 + 单测。
2. 再落 D2（守卫）：新增 `_has_active_admin_run_for_spec` + 两个派发点接入 + 单测（在飞/异常 fail-open/无在飞三例）。
3. 最后落 D3+D4（排程与计数）：`_handle_scenario_repaired` 两态分支 + 计数读写 + 清零点（`_record_verdict_adoption` / `unfreeze_spec`）+ 单测（首次排程不升级 / 再次升级 / 重验重获预算 / 两处清零 / admin 复位不清零）。
4. 回滚：三步互相独立，任一步可单独 revert；D3 若需回滚，删除排程与计数即可回到「只写 error」旧行为（`_dispatch_backoff_until` 为通用字段，无害）。

## Open Questions

- `agents.scenario_repair_retry_delay_minutes` 是否需要入 config？倾向**不入**（内部派生常量 30 分钟，与 `poll_interval_minutes` 对齐），除非实现时出现明确的运维调优需求——按「新增配置项必须带 Dashboard 界面」的约定，不入 config 反而更省事。
- 探测器侧是否需要同步豁免（Risk 1）？倾向**本轮不动**，先观察 D2 守卫是否足够降噪。
