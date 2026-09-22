# orphaned-state-probe-calibration 设计

## 现状（实测复核，行号以复核时 main 为准）

- `_RUN_PREFIXES`（core/admin_monitor.py:280）**自述是失败计数子集**（注释「只列计入失败统计的前缀」），却被 `_spec_from_run_id`（core/admin_monitor.py:2352，循环 :2363）唯一消费。该函数同时服务两类调用点：活跃度/归属判定（`_has_recent_spec_run` :374、`_has_recent_progress` :2415、:907 进程归属）与**失败计数**（`_detect_repeated_failures` :800，阈值 3 次/30 分钟）。一张表两种语义，是本 SPEC 必须拆开的结构性约束。
- 本次误报机理：`repair-` 既不在 `_RUN_PREFIXES`，也不在 `_pgrep_live_worktree`（core/admin_monitor.py:335，模式仅 impl-/verify-）的匹配集。`spec_is_undriven`（:384）条件 ①（:427→:357）与 ②（:424→:335）**同时为假**，三条件全真 → 误判（实证：.fenix/logs/fenixd.log:12461 报警，:12370-12376 显示 repair run 09:30:12 起活跃推进）。
- event_bus 恢复链复用同一判定：`from core.admin_monitor import spec_is_undriven`（core/event_bus.py:244），故条件 ① 的修复自动传导至恢复出口；core/event_bus.py:344 另有同语义 pgrep 孪生（供 :333 轻量存活探测），不在该链上，需一并同步。
- admin 处置失败：`run_administrator` 定义在 core/agent_runner/maintenance_runs.py:52（core/agent_runner/runner.py:956 仅门面转导），其 except 分支 `error = str(e)`（maintenance_runs.py:148 附近）取 `_run_claude` 抛出的 `RuntimeError` 文本。该异常**已携带原始证据**：`exc.stderr_lines`、`exc.exit_code`（core/agent_runner/runner.py:2983-2985），stderr 本身也已写入 run 产物（runner.py:2692 `{"type":"stderr","line":…}`）。文本退化为 `Exit code: N` 的真因是 `_denoise_stderr`（runner.py:3006-3022）丢弃 `^\[claude-code:` 行。
- run 产物取证可行性（实测 .fenix/runs/archive/admin-fix-dashboard-read-path-performance-1789583548.jsonl）：assistant/user 事件带 ISO `timestamp`，而 `provider_marker` / `system` / `stderr` / `result` / `error` 五类事件**无 timestamp 字段**。`provider_marker` 事件携带 provider+model，是定位「模型不被网关接受」类失败的关键证据。

## 改动设计

1. **前缀语义拆分（不得混用一张表）**
   - spec 名归一（`_spec_from_run_id`）改用真源全量前缀 `core/agent_runner/run_files.py:RUN_ID_AGENT_PREFIXES`（顺序敏感：长前缀在前，顺序与真源一致，含 `repair-`）。
   - 失败计数（`_detect_repeated_failures` :800）保留**显式失败前缀子集**常量，且**保留常量名 `_RUN_PREFIXES`**（tests/test_dashboard_data.py:586-590 与 tests/test_deliverable_declaration_triage.py:423-427,450-456 直接 import 该名；改名或删除会造成 ImportError）。
   - 子集内**补入 `repair-`**（repair 属实现通道，失败即实现失败）；`planner-` / `test-` 仍不计入。该计入/不计入边界必须在 tests/test_admin.py 中锁定（见 tasks 2.4）。
   - 若实现选择「整表替换」（`_RUN_PREFIXES = tuple(p for p, _ in RUN_ID_AGENT_PREFIXES)`），则 `repeated_failures` 语义同时扩大（planner-/test- 失败 run 计入），MUST 在 tasks 中显式声明并补测试，不得沿用「仅影响匹配广度、既有行为不变」的结论。
2. **活跃度判定回归**：`_has_recent_spec_run` 补 repair 前缀用例（mtime 新鲜 → True，三条件 ① 不成立）。
3. **存活探测覆盖 repair**：`_pgrep_live_worktree`（core/admin_monitor.py:335）模式集加入 `repair`（`repair-<spec>-`），并同步 core/event_bus.py:344 孪生。理由：仅修条件 ① 时，若 repair run 事件间隙超过 `ORPHANED_RUN_GRACE_SECONDS = 120`（core/admin_monitor.py:98；本次 run p90 30.7s、max 95.3s，已贴近该窗口）仍会复现同类误报。
4. **Exit 证据（改动落点在 maintenance_runs.py:148 附近 except 分支，不改 runner.py 的 error 归因文本语义）**
   - 原始 stderr 尾部：取 `getattr(e, "stderr_lines", [])` 末 N 行、截断 4KB，写入**独立证据字段/logger context 与 AdminDisposition 证据**，不进 `error` 文本——error-attribution-denoise D5 的全局降噪结论保持不变；
   - 退出码：`getattr(e, "exit_code", None)`；
   - provider/model：读同一 run 产物内的 `provider_marker` 事件；
   - run 末 **3 条带 timestamp 的事件**时间戳：取数时 MUST 跳过无 timestamp 事件（终态 error/stderr/result/provider_marker/system 均无该字段，否则恒为空）。
   - 以上四项对处置流程零影响：`AdminDisposition.result`/`escalate` 判定不变。
5. **去重语义文档化**：在 admin_monitor 注释与告警 description 中区分 signal / disposition pending / disposition failed / escalated 生命周期阶段；冷却查重已由 `_throttled`（core/admin_monitor.py:1242-1247，内部 `AdminStore.latest_signal`）承担，保持现状不动（实证：.fenix/logs/fenixd.log:17224 `Signal throttled: orphaned_state … (cooldown 15m)`）。注意：冷却窗口过期后同信号会再次成条，属既有节流语义而非文档缺陷——文档只描述阶段差异，不得声称「同一信号永远只出现一条记录」。

## 兼容与风险

- 归一改用全量前缀：活跃度/归属判定只会更少误报；但**必须**按设计 1 拆分，否则 `repeated_failures`（3 次/30 分钟）会连带把 planner-/test- 失败 run 纳入，产生新告警类别——除 `repair-` 的显式补入外，本 SPEC 不承担该行为变化。
- 条件 ② 扩大模式集只增加「进程存活」判据命中面：孤儿定义要求三条件同时成立，故只会减少误报，不会漏报真孤儿。
- 既有同源哨测试（tests/test_dashboard_data.py:585、tests/test_deliverable_declaration_triage.py:421,448）在「保留 `_RUN_PREFIXES` 名 + 补 `repair-`」方案下无需修改即保持绿色（`repair-` 已在真源中，`run_spec_part("repair-myspec-<ts>") == "myspec"`）；实现时须实测确认，不得凭推断跳过回归。
