# Findings Ledger — fix-deferred-findings

本账目基于 design D1 逐条账目（14 条 = dashboard 4 条 + verification 10 条），
登记本变更落地后的最终态。每条含：目标状态 / 行为变化标记 / 测试证据。

## 已修复（8 条）

| # | 条目 | 位置 | 行为变化 | 测试证据 | 状态 |
|---|---|---|---|---|---|
| 1 | `_timeline_sort_key` 无效时间戳抛 TypeError（P0 真 bug） | `timeline.py` | **有意修复**（无效事件排到末尾，不再崩溃） | `test_timeline_sort_key_invalid_time_sorts_later` 改写为断言排序结果；`test_parse_iso_ts_naive_interpreted_as_utc` | ✅ 已修 |
| 2 | `_port_responds` 串行探测 51 端口（两处） | `serving.py` | 零变化（结果集不变） | `test_concurrent_probe_matches_serial_pre_set` / `test_concurrent_probe_no_responding_ports` / `test_probe_all_ports_responding` | ✅ 已修 |
| 3 | 3 处重复 late-import `import re as _re` | `serving.py`（2 处）、`infra_classify.py`（1 处） | 零变化 | 无（顶部已有 `import re`，删冗余） | ✅ 已修 |
| 4 | `_escalate_env_blocked` evidence 截断无省略号 | `escalation.py` | 有意（微） | `test_long_violation_message_gets_ellipsis_marker` / `test_short_message_without_ellipsis` | ✅ 已修 |
| 5 | `_record_verdict_adoption` token 基线静默 fallback | `verdict_evidence.py` | 有意（微，仅加告警） | `test_corrupt_baseline_triggers_warning` | ✅ 已修 |
| 6 | legacy / `_read_verdict` 共享文件 fallback 路径重复 | `legacy.py`、`report_gate.py` | 零变化 | 无（helper `_verify_progress_result_paths` 落 `report_gate.py`，三处调用点统一） | ✅ 已修 |
| 7 | `_ensure_serving_worktree` 中 `stop()` except 仅 pass | `serving.py` | 有意（微，仅加日志） | 无（对齐 `_evict_spec_serving` 样板） | ✅ 已修 |
| 8 | CYC-1 反向 import（分层倒置，非 engine.py 子项） | `escalation.py`、`report_gate.py`、`event_bus.py`、dashboard 门面、`core/signals.py`（新） | 零变化（搬迁经门面 re-export 保持导入路径） | `test_no_direct_import_in_pm_engine_submodules` / `test_signals_functions_accessible_from_pm_engine` | ✅ 已修 |

## 记录不修（4 条，理由见 design D1「记录不修」表）

| 条目 | 位置 | 不修理由 | 状态 |
|---|---|---|---|
| `_should_overlay` done/pushed 叠加语义 | `dashboard/data/tasks.py` | 注释已自证刻意（覆盖实现者从不勾 tasks.md）；三用例已锁定现行为 | 📝 记录不修 |
| `shell=True` 注入面 | `verification/serving.py`（3 处 `Popen`） | shell 展开是有意设计；信任边界 = `.fenix/verify.yaml` 写权限，属已接受风险 | 📝 记录不修 |
| config 缓存键（OBS-1） | `dashboard/data/config_admin.py` | `read_config` 已无缓存（清单描述过时）；`read_effective_config` 的键含门面 `USER_CONFIG_PATH` 恰是测试期望的正确语义 | 📝 记录不修 |
| `max(1, base >> (attempts-1))` 位移降档（B5） | `verification/escalation.py:124` | 正整数上位移与向下取整除法严格等价，改写纯 churn；现有测试锁数值结果 | 📝 记录不修 |

## 转移（2 条，转移去向见 design D3 转移清单）

| 条目 | 落点 | 转移去向 | 状态 |
|---|---|---|---|
| CYC-1 反向 import（A3）的 `engine.py` 子项 | `core/pm_engine/engine.py:21` | `refactor-facade-delegation`（其触及 engine.py）或合并后单独清理 | 🔄 转移 |
| `_last_freeze_rejected*` 未声明（B4） | `verification/pipeline.py` | `refactor-facade-delegation`（其触及 pipeline.py） | 🔄 转移 |
| 陈旧 docstring D3 引用（B6） | `verification/pipeline.py` | 同上 | 🔄 转移 |

## CYC-1 搬迁登记（design D3 约定 2）

- `get_runs` / `record_project_event` **登记为「不搬」**：pm_engine 侧唯一进口为
  engine.py:21（已登记为转移清单），搬迁不减少任何非 engine.py 反向 import；
  且 `get_runs` 的读路径（`_RUN_META_CACHE` / `_run_meta_cached` memo 语义）刚由
  `fix-dashboard-read-path-performance` 完成优化，design D3 约定 2 明示
  MUST NOT 为达成此项而改动缓存/读路径逻辑。故本变更实际搬入中性模块的
  函数为 `request_admin_invoke`（escalation.py 消费）与 `parse_verify_progress`
  （report_gate.py 消费）——正是 pm_engine 侧全部非 engine.py 消费点。
- `find_impl_run_file` / `parse_run_task_done` 零搬移：`event_bus.py:477` 消费点
  已直接改从真源 `core.run_task_track` 导入（engine.py 那一行按 D3 转移）。

## 基线比对（5.1）

`python3 bin/run_full_suite.py --timeout 3600 --baseline main`：
- 分类 = **存量**（当前失败集合 ⊆ 基线失败集合，无新增失败）
- 当前失败 6 项、基线失败 7 项；差异项 `test_callsite_arity_guard` 在基线失败
  而当前通过（本变更未触及该文件，属基线环境波动）。
