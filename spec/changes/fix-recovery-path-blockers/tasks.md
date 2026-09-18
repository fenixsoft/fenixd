## Deliverables

```yaml
- path: core/admin_monitor.py
  kind: modify
- path: core/event_bus.py
  kind: modify
- path: core/state_machine.py
  kind: modify
- path: core/pm_engine/verification/pipeline.py
  kind: modify
- path: core/pm_engine/verification/escalation.py
  kind: modify
- path: core/pm_engine/verification/verdict_evidence.py
  kind: modify
- path: tests/test_admin.py
  kind: modify
- path: tests/test_event_bus.py
  kind: modify
- path: tests/test_pm_verification.py
  kind: modify
```

## 1. 驱动判定修正（缺口 A：admin run 不再计入驱动证据）

- [ ] 1.1 在 `core/admin_monitor.py` 抽出模块级辅助 `_is_admin_run_id(stem)`（判定 `admin-` 前缀；与 `RUN_ID_AGENT_PREFIXES` 同源，禁硬编码字符串散落），供 `_has_recent_spec_run` 与 `AdminMonitor._has_recent_progress` 共用，并在注释中标注「单点定义，两处委托，勿二次漂移」
- [ ] 1.2 修改模块级 `_has_recent_spec_run`：glob 后跳过 `admin-` 前缀的 run 文件（判定口径变为「存在非 admin 前缀的近期 run 文件」），docstring 说明语义变更与事故出处
- [ ] 1.3 修改 `AdminMonitor._has_recent_progress` 同步该排除（委托 1.1 的辅助函数），保持与模块级函数同源
- [ ] 1.4 在 `tests/test_admin.py` 新增 `TestAdminRunNotDriverEvidence` 三用例：①仅 admin run（mtime 新鲜）→ `_has_recent_spec_run` False 且 `spec_is_undriven` True；②admin + impl 混合 → 两者分别为 True/False；③admin run 过期 → 与无 run 文件逐位一致
- [ ] 1.5 运行 `python3 -m pytest tests/test_admin.py -q -k "OrphanedRepairProbe or AdminRunNotDriverEvidence" ` 确认新增用例通过且既有 repair 前缀用例（`test_active_repair_run_suppresses_undriven`）不回归

## 2. 派发互斥守卫（缺口 A：verifier 与在飞 admin run）

- [ ] 2.1 在 `core/admin_monitor.py` 的 `AdminMonitor` 新增 `_has_active_admin_run_for_spec(spec) -> bool`：按 `(spec)` 单键聚合 store 中 `kind == DISPOSITION` 的记录（口径复用 `_has_active_admin_run_for` 的 by_run 归并：某 `admin_run_id` 组 `has_pending` 且无终结兄弟记录），覆盖该 SPEC 的**任意** signal_type；判定异常 fail-open 返回 False 并记 WARNING。**同源逻辑以模块级私有函数抽出**（store 作为入参），供 `AdminMonitor` 方法与此处两个 `event_bus` 调用点共用，MUST NOT 复制第二份归并实现
- [ ] 2.2 在 `core/admin_monitor.py` 的 `_reset_orphaned_after_disposition` 派发 verifier 前插入守卫：`_has_active_admin_run_for_spec(spec)` 为真则跳过 `handle_event("spec_implemented", ...)` 并记 INFO 日志，SPEC 状态保持原样（MUST NOT 因此写额外状态）
- [ ] 2.3 在 `core/event_bus.py` 的 `_recover_testing` 中，`spec_is_undriven` 通过后、`handle_event("spec_implemented", ...)` 之前插入同一守卫。**取用面（design D2）**：`PMEngine`/`PipelineContext` 均**不持有** `admin_monitor` 引用，MUST NOT 假其可达；守卫经两条**无需新注入**的通路取用并联——(a) `AdminStore(pm_engine.project_root, logger)` 是纯路径构造（`core/admin_store.py:56-61`），读 `read_all()` 后套 2.1 的同源归并；(b) `pm_engine.agent_runner.running_run_ids()`（`core/agent_runner/runner.py:4320`）中存在 `admin-<spec>-` 前缀 run（admin run 经 `_run_claude` 注册进 `_running_agents`，`runner.py:3372`）。任一成立即跳过派发；两路皆异常时 fail-open 放行并记 WARNING
- [ ] 2.4 在 `core/admin_monitor.py` 的 `_handle_signal` 中，`_throttled` 通过后、`_invoke_administrator` **之前**插入同一守卫：`_has_active_admin_run_for_spec(spec)` 为真则跳过本次唤起并记 INFO/WARNING，信号仍按既有沉淀/节流语义落 store（不丢痕）。依据：`_has_active_admin_run_for` 当前仅用于 `_recover_orphaned_dispositions` 重派判重（`core/admin_monitor.py:1819`），唤起路径无在飞去重，而 D1 生效后处置中的 spec 会在冷却窗（缺省 60 分钟，`core/config.py:1051`）过期后重新成条 → 产生与在飞处置并行的第二个 admin run（design D2b）
- [ ] 2.5 在 `tests/test_admin.py` 新增守卫用例：①在飞 admin run（pending 且无终结兄弟）→ `_reset_orphaned_after_disposition` 不派发 verifier；②admin 判定抛异常 → fail-open 仍派发（印证不阻断恢复）；③无在飞 admin → 正常派发；④`_handle_signal` 在存在在飞 admin run 时 `_invoke_administrator` 不被调用（且信号仍落 store）；⑤守卫覆盖非 `orphaned_state` 的 signal_type（如 `verify_env_blocked`）
- [ ] 2.6 在 `tests/test_event_bus.py` 新增 `_recover_testing` 守卫用例：①在飞 admin run 存在时 `handle_event` 不被调用、日志含跳过说明；②无 admin 时被调用一次；③经 `AdminStore` 通路（不可用 `pm_engine.admin_monitor`）判定在飞 —— 覆盖 2.3 的两条取用通路

## 3. 预算耗尽重验日程（缺口 B：首次排程 / 再次升级）

- [ ] 3.1 在 `core/state_machine.py` 新增字段名常量 `SCENARIO_REPAIR_EXHAUSTED_FIELD = "_scenario_repair_exhausted_rounds"` 并在注释中登记其生命周期（清零点：`verified` 落定 + `unfreeze_spec`；admin 处置复位**不**清零），与 `_judge_rerun_count` 常量并列
- [ ] 3.2 在 `core/state_machine.py` 的 `unfreeze_spec` 中把该字段一并清零（与既有 `_env_block_rounds` / `_judge_rerun_count` 的清零点对齐）
- [ ] 3.3 在 `core/pm_engine/verification/verdict_evidence.py` 的 `_record_verdict_adoption` 既有 `status == "verified"` 分支中，把该字段与 `_judge_rerun_count` 一并清零
- [ ] 3.4 在 `core/pm_engine/verification/escalation.py` 新增 `_schedule_scenario_repair_reverify(pipeline, spec_name) -> None`：写 `_dispatch_backoff_until`（deadline = now + 重验延时常量）+ 排程 `threading.Timer`（到期回调经 `pipeline._context.enqueue(spec_name, "verifier")` 等价路径触发重验；daemon 定时器模式仿 `_schedule_instant_fail_recovery`（`core/pm_engine/dispatch/backoff.py:120-165`），**per-spec 判重保证幂等**，MUST 用与既有定时器族同款的去重集合/标记，MUST NOT 新增第二套派发判据）；模块级常量 `_SCENARIO_REPAIR_REVERIFY_DELAY_SECONDS = 1800`（与 `poll_interval_minutes` 对齐）并在 docstring 说明「定时器管准点、周期扫描管兜底（兜底落点 = `event_bus._recover_testing` 的 `schedule.poll_interval_minutes` 扫描，MUST NOT 误引 `check_scheduling_deadlines`——它只覆盖 drafted/ready）」
- [ ] 3.5 改造 `core/pm_engine/verification/pipeline.py` 的 `_handle_scenario_repaired` 预算耗尽分支为两态，**先读计数、再分两条不同文案写**（既有实现无条件写同一文案，`core/pm_engine/verification/pipeline.py:988-995`；MUST NOT 先写旧文案再补写，否则首次排程的「下次重验时刻」被立即覆盖）：为 0 → 调 3.4 的排程器 + 计数写 1 + error 文案含明确下次重验时刻（ISO8601 UTC）+ MUST NOT 调 `escalation_notifier`；`>= 1` → 走既有升级通道（保持 testing，不排程）。error 文案 MUST NOT 命中 `FREEZE_ERROR_PREFIX` / `task-gap` 等既有读侧语义前缀
- [ ] 3.6 在 `tests/test_pm_verification.py` 新增/扩展用例：①首次耗尽 → 计数 1、排程生效（`_dispatch_backoff_until` 已写）、未调 `escalation_notifier`、error 含重验时刻且**未被旧文案覆盖**；②再次耗尽 → 调 `escalation_notifier` 且未新增排程；③排程幂等（重复进入首次态不排第二个定时器）；④排程触发的重验轮 `_repair_depth` 从 0 起算（可重获完整 `_SCENARIO_REPAIR_MAX_ROUNDS`）；⑤`verified` 落定清零；⑥`unfreeze_spec` 清零；⑦admin 处置复位（`transition_gate(testing)`）不清零
- [ ] 3.7 运行 `python3 -m pytest tests/test_pm_verification.py tests/test_admin.py tests/test_event_bus.py tests/test_scenario_reroute_gate.py -q` 确认全绿（含既有 `test_repair_reenters_execution_and_budget_exhausts` 不回归）

## 4. 回归与收口

- [ ] 4.1 运行有界全量回归 `python3 bin/run_full_suite.py --timeout 3600 --baseline HEAD`（fix-run-hang-amplification 3.3：MUST NOT 裸调 `pytest tests/ -q`），按输出归类存量/引入失败
- [ ] 4.2 在 `tasks.md` 勾选全部已完成任务并写 `.fenix-run-result.json`（`status: success`，附改动摘要与回归结论）
