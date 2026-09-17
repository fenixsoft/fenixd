# Tasks: fix-robustness-edge-cases

## Deliverables

```yaml
- path: core/agent_runner/run_files.py
  kind: modify
- path: core/pm_engine/budget.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: core/agent_runner/liveness.py
  kind: modify
- path: core/worktree_manager.py
  kind: modify
- path: core/run_task_track.py
  kind: modify
- path: core/admin_store.py
  kind: modify
- path: core/logger.py
  kind: modify
- path: core/verify_scenarios.py
  kind: modify
- path: core/pm_engine/spec_integrity.py
  kind: modify
- path: core/dashboard/server.py
  kind: modify
- path: core/verify_engine/scenario_static_check.py
  kind: modify
- path: core/verify_engine/screenshot_lab.py
  kind: modify
- path: core/fast_track_result.py
  kind: modify
- path: core/dashboard/registry.py
  kind: modify
- path: core/pm_engine/verification/judge_gate.py
  kind: modify
- path: core/dashboard/data/spec_archive.py
  kind: modify
- path: tests/test_run_spec_prefixed_attribution.py
  kind: new
- path: tests/test_admin_store_corruption.py
  kind: new
- path: tests/test_logger_no_bypass.py
  kind: new
```

> 路径说明（planner 耗时点，条件式）：`core/pm_engine/verification.py` 已列入 Deliverables。若实现时前序 `refactor-verification-module` **尚未落地**（现状：该文件仍为 6304 行单文件、`core/pm_engine/verification/` 包不存在），则直接改 `core/pm_engine/verification.py`；若**已落地**，则改其派生模块并把该派生模块路径补入 Deliverables。不得在未列入 Deliverables 的文件上实现本 SPEC 的改动。**实现时状态**：refactor-verification-module 已落地（`core/pm_engine/verification/` 包存在），planner 耗时点落在派生模块 `core/pm_engine/verification/judge_gate.py`（`_last_planner_run_cost`），已补入 Deliverables。另：`core/dashboard/data/spec_archive.py`（原子串 glob 点，承接方 refactor-dashboard-data-module / fix-dashboard-read-path-performance 均已合入）随本 SPEC 纳入修正，已补入 Deliverables。

## 1. spec 归属全等匹配

- [x] 1.0 **（前置，必须先做）补齐 `run_spec_part` 后缀解析**：`core/agent_runner/run_files.py:66` 现仅剥 `-a<n>` 与时间戳、不识别 `-r<n>`；实测 `.fenix/runs/` 有 **40 个** `<prefix>-<spec>-<ts>-a<n>-r<m>.jsonl` 文件（如 `impl-add-control-plane-silent-failure-guards-1789419431-a1-r1.jsonl`）会被解析成整段而非 spec 名。改为同时剥离 `-a<n>` 与 `-r<n>`（参考 `core/admin_monitor.py:1856 _spec_from_run_id` 的 `^(.*)-\d{9,10}(-(?:a|r)\d+)*$`，但前缀表仍以 `RUN_ID_AGENT_PREFIXES` 为唯一真源）。**本步未完成前不得进入 1.1**——直接上全等守卫会把在跑的 run 判为「非本 spec」，活性/活动判定取假、预算豁免失效、`find_impl_run_file` 取到旧产物，即误报 stuck；该错误模式有前次事故记录（见 `_spec_from_run_id` docstring 引用的 evo-verifier-result-single-source）。
- [x] 1.1 枚举全部「按 spec 名查 run 流」判定点并逐一改为「glob 后经 `run_spec_part` 解析全等比较」。**完整清单（实测 file:line）**：`core/pm_engine/budget.py:336`（archive 目录）、`core/pm_engine/budget.py:355`、`core/pm_engine/engine.py:1986`、`core/pm_engine/verification.py:4174`（planner-plan）、`core/agent_runner/liveness.py:284`、`core/worktree_manager.py:1265`、`core/run_task_track.py:74`。**另有两处同型但形态更宽，必须给出显式处置（纳入本 SPEC 或书面 defer 并注明承接方）**：① `core/dashboard/data.py:1038` 用 `glob(f"*{spec}*.jsonl")` **子串**匹配 run 文件，比前缀 glob 更易误命中，已构成 spec.md「所有按 spec 名查找 run 流文件的判定点 MUST 全等」的违约，但该文件归属 `refactor-dashboard-data-module` / `fix-dashboard-read-path-performance`，须写明由谁承接；② `core/admin_monitor.py:280-295` 与 `core/event_bus.py:339-350` 的 `_pgrep_live_worktree` 以 `pgrep -f "impl-<spec>-"` 子串匹配 worktree 目录名，spec 名互为前缀时误判活性——不在本 requirement 的「run 流文件」字面范围内，处置须写明。
- [x] 1.2 确认 `run_spec_part` 为唯一解析来源，无新增重复实现；同时记录与 `admin_monitor._spec_from_run_id`（`core/admin_monitor.py:1856`）的关系——1.0 完成后二者对 `-r<n>` 口径应一致，须在注释或提交信息中说明，避免再次漂移
- [x] 1.3 新增 `tests/test_run_spec_prefixed_attribution.py`：构造 `impl-fix-x-*` 与 `impl-fix-x-y-*` 断言各判定点不误归属；**并覆盖后缀形态** `impl-fix-x-<ts>-a1.jsonl` 与 `impl-fix-x-<ts>-a1-r2.jsonl`（断言仍归属 `fix-x`，即「加守卫不漏命中」）
- [x] 1.4 全量 pytest（重点 `test_pm_recovery`、`test_dispatch_aging`、`test_worktree_stray_and_identical`、`test_dashboard_*`），独立 commit

## 2. admin_store 抗损坏

- [x] 2.1 `_read_unlocked`：解析失败时先把文件改名 `.corrupt-<ts>` 留底，再返回 `[]`，并产生一条可观测记录
- [x] 2.2 `_mutate` 写回前加下限保护：旧记录整体丢失时拒绝写回并告警
- [x] 2.3 新增 `tests/test_admin_store_corruption.py`：损坏留底、拒绝清库写回、**损坏后恢复写入（留底后新告警仍能写入，不被下限保护误拦）**、正常追加、合法空文件不被误拦 五场景
- [x] 2.4 全量 pytest（重点 `test_alert_lifecycle`、`test_admin`），独立 commit

## 3. logger 门面统一

- [x] 3.1 收敛旁路 logger（实测清单，file:line）：`core/verify_scenarios.py:183,263`（`getLogger("pm_engine")`）、`core/pm_engine/spec_integrity.py:61`（同）、`core/dashboard/server.py:77`、`core/dashboard/registry.py:29,31`、`core/verify_engine/scenario_static_check.py:29`、**`core/verify_engine/screenshot_lab.py:31`**、**`core/fast_track_result.py:141`**（后两者原不在清单与 Deliverables 内，但 3.2 的静态检查会检出——已补入）改为 `fenixd.` 可传播层级或注入 Logger；改动 `logging.getLogger("pm_engine")` 名称时须确认无按名捕获的消费方/测试
- [x] 3.2 新增 `tests/test_logger_no_bypass.py`：静态扫描 core，断言无裸 `logging.getLogger(...)`（`fenixd` 层级除外）
- [x] 3.3 修复 `core/logger.py` 中绕过级别判定的记录路径（`Logger._log` 直接调 `self._python_logger.handle(record)`，绕开 `isEnabledFor`，使 `logging.level` 失效、DEBUG 恒落盘）；修复后既有 `debug(...)` 调用（`core/event_bus.py` 6 处、`core/evolution.py` 7 处、`core/admin_monitor.py` 4 处等，且多处以 `Logger(proot)` 默认 INFO 实例化，如 `core/dashboard/data.py:422,466,495`）将不再落盘——MUST 先确认无消费方/测试依赖 DEBUG 行，再改
- [x] 3.4 实证：「持久化集加载净化剔除」类告警出现在 `fenixd.log`；全量 pytest，独立 commit

## 4. 收尾

- [x] 4.1 全量 `bin/run_full_suite.py` + 三项缺陷的复现用例全绿
- [ ] 4.2 经用户确认时机后重启 daemon 并冒烟验证
