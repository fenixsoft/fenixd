# Tasks: refactor-dashboard-data-module

## Deliverables

```yaml
- path: core/dashboard/data/__init__.py
  kind: new
- path: core/dashboard/data/state.py
  kind: new
- path: core/dashboard/data/admin_alerts.py
  kind: new
- path: core/dashboard/data/admin_actions.py
  kind: new
- path: core/dashboard/data/spec_archive.py
  kind: new
- path: core/dashboard/data/spec_docs.py
  kind: new
- path: core/dashboard/data/tasks.py
  kind: new
- path: core/dashboard/data/log_index.py
  kind: new
- path: core/dashboard/data/artifacts.py
  kind: new
- path: core/dashboard/data/runs.py
  kind: new
- path: core/dashboard/data/timeline.py
  kind: new
- path: core/dashboard/data/summary.py
  kind: new
- path: core/dashboard/data/config_admin.py
  kind: new
- path: core/dashboard/data/evolution_items.py
  kind: new
- path: core/dashboard/data/_legacy.py
  kind: reference  # 阶段 1 由 core/dashboard/data.py `git mv` 改名而来（D7 过渡载体），阶段 4 删除
- path: core/dashboard/data.py
  kind: delete
- path: tests/test_characterization_dashboard_data.py
  kind: new
- path: tests/test_dashboard_data_modules_contract.py
  kind: new
- path: core/dashboard/server.py
  kind: reference
- path: core/pm_engine/engine.py
  kind: reference
```

## 1. 阶段 0：测试基线加固

- [x] 1.1 静态清点：用 `grep`/AST 提取 `core/dashboard/data.py` 的**全部顶层公开名、下划线私有别名、模块级常量、以及导入进来被二次导出的名字（如 `_is_running`、`USER_CONFIG_PATH`）**，以及全仓对 `core.dashboard.data` 的属性访问清单，落盘为待验证契约清单文件（置于 spec 目录，如 `contract-inventory.md`）
  - 注意：**只扫 AST 顶层 `def`/`class` 会漏**（兼容别名块 `_parse_run_task_done`/`_find_impl_run_file` 与 32 个模块级常量都不是 `def`）。清点必须覆盖四类：函数、类、顶层赋值/别名、`import ... as` 绑定。
  - 清点结果 MUST 与 design.md D3 分组表逐名对齐，列出「表中未出现但存在于 data.py 的名字」，不得留下未归属项（当前实测：118 个 function/class + 32 个常量/别名 = 150 个顶层名字，其中 `_is_running`、`USER_CONFIG_PATH` 留在门面，其余随组迁移）。
- [x] 1.2 为将被搬移且当前无测试覆盖的函数补 characterization tests（新增 `tests/test_characterization_dashboard_data.py`，不改现有测试文件）
- [x] 1.2b 为 D8 两处 **patch 语义** 补锁定测试：`patch("core.dashboard.data._is_running")` 必须影响 `daemon_health` 的行为、`patch("core.dashboard.data.USER_CONFIG_PATH")` 必须影响配置读取路径（复用 `tests/test_config.py:397-432`、`tests/test_dashboard_data.py:721` 的既有断言形态）
- [x] 1.3 建立疑点清单文件（如 `findings.md`），自本阶段起持续维护：拆分中发现的 bug/死代码/循环依赖只记录不修
- [x] 1.4 运行 `bin/run_full_suite.py` 记录重构前基线失败集合

## 2. 阶段 1：叶子组搬移

- [x] 2.1 **改名入包（MUST 先做，见 design D7）**：`git mv core/dashboard/data.py core/dashboard/data/_legacy.py`；新建 `core/dashboard/data/__init__.py`，逐条 `from ._legacy import <name>` 显式 re-export `_legacy` 的**全部**名字（函数 + 类 + 下划线名 + 32 个模块级常量 + `_is_running` / `USER_CONFIG_PATH`；禁用 `import *`）。本步骤完成后立即全量 pytest，确认与阶段 0 基线一致
  - 原因：Python 解析同名「包」优先于「模块」（`importlib/_bootstrap_external.py:1557-1564`），`data/__init__.py` 一旦存在，`data.py` 即不可达。若按「先建空包」执行，未搬移的约 100 个函数会当场消失，阶段 1 起全量 pytest 必红、D4 的分阶段全绿与回滚粒度失效。
  - `_is_running` / `USER_CONFIG_PATH` 在本步骤即固定为**门面绑定**（D2/D8），此后各阶段 MUST NOT 将它们迁入子模块。
- [x] 2.2 搬移 `state` 组：`parse_state` → `core/dashboard/data/state.py`
- [x] 2.3 搬移 `evolution_items` 组：`read_evolution_items` / `read_evolution_analysis` / `read_evolution_draft` / `EVOLUTION_DOC_WHITELIST` → `evolution_items.py`
- [x] 2.4 搬移 `log_index` 组：`_log_index_path` / `_build_log_block_index` / `_write_log_index` / `_update_log_block_index` / `_load_log_index` / `_read_log_tail_window` / `_iter_tail_log_entries` / `_norm_utc_iso` / `_read_log_window_from` / `get_recent_events` / `record_project_event` / `LOG_INDEX_BLOCK` / `LOG_INDEX_TAIL_WINDOW` / `_LOG_INDEX_REBUILDS` → `log_index.py`
- [x] 2.5 搬移 `tasks` 组：`parse_tasks` / `task_progress` / `tasks_note` / `run_task_progress` / `_should_overlay` / `_LIVE_OVERLAY_STATUSES` / `find_implementer_worktree` / `_parse_run_task_done` / `_find_impl_run_file` → `tasks.py`（兼容别名块 MUST 一并迁移并在门面保持同名绑定，spec 的「私有别名可访问」场景依赖它；复核调用点 `run_task_progress` 与 `core/run_task_track.py:91` 的引用）
- [x] 2.6 门面 re-export 本阶段全部符号（改为从新子模块 re-export 已摘出组，其余仍从 `_legacy`）；运行全量 pytest 与 import 校验，独立 commit

## 3. 阶段 2：中层组搬移

- [x] 3.1 搬移 `admin_alerts` 组：`get_alerts` / `get_unhandled_alerts` / `get_resolved_alerts` / `mark_alert_handled` / `mark_all_alerts_handled` / `alerts_summary` / `get_admin_activities` → `admin_alerts.py`
- [x] 3.2 搬移 `spec_docs` 组：`resolve_spec_dir` / `InvalidSpecName` / `InvalidSpecDoc` / `InvalidPriority` / `get_spec_doc` / `_read_spec_scenarios` / `count_scenarios` / `count_generated_scenarios` / `spec_generation_progress` → `spec_docs.py`
- [x] 3.3 搬移 `spec_archive` 组：`soft_delete_spec` / `archive_spec` / `is_spec_archived` / `auto_archive_check` → `spec_archive.py`
- [x] 3.4 搬移 `admin_actions` 组：`request_admin_invoke` / `request_run_cancel` / `freeze_spec` / `unfreeze_spec` / `is_spec_frozen` / `promote_spec` / `reflow_spec` / `re_review_spec` / `reclassify_infra_rounds` / `_write_scheduling_kick_signal` / `get_spec_start_after` / `set_spec_start_after` / `get_frozen_until` / `configure_spec_freeze` / `set_spec_budget` / `request_spec_approve_push` / `clear_spec_error` / `set_spec_priority` → `admin_actions.py`
- [x] 3.5 门面 re-export 本阶段全部符号；运行全量 pytest 与 import 校验，独立 commit

## 4. 阶段 3：中枢组搬移

- [x] 4.0 分组常量归属（随组迁移，MUST 与函数同迁避免状态分叉，见 design D2/D3）：`admin_actions.py` ← `ADMIN_INVOKE_REQUEST` / `CANCEL_RUN_REQUEST` / `SCHEDULING_KICK_REQUEST` / `APPROVE_PUSH_REQUEST`；`spec_docs.py` ← `_SPEC_NAME_RE` / `_SPEC_DOC_WHITELIST`；`summary.py` ← `_DAEMON_HEALTH_TTL` / `_DAEMON_HEALTH_CACHE` / `_HOSTING_STATE_TTL` / `_HOSTING_STATE_CACHE` / `_GLOBAL_BUDGET_CACHE` / `_GLOBAL_BUDGET_CACHE_MAX`；`config_admin.py` ← `_MANAGED_KEYS` / `_AGENTS_MANAGED_SUBKEYS` / `USER_CONFIG_PATH` **除外（留门面，见 D8）** / `_SOURCE_KEYS` / `_DEFAULT_SELF_REVIEW` / `_CONFIG_HEADER_COMMENT` / `_ADMIN_DEFAULTS` / `_EFFECTIVE_CONFIG_CACHE` / `_EFFECTIVE_CONFIG_CACHE_MAX` / `_SYNC_PAGE_KEYS`。迁移后 MUST 复核清点清单，确认无顶层名字既未迁出也未留在门面
- [x] 4.1 搬移 `artifacts` 组：`parse_verify_progress` / `parse_report` / `parse_test_scenarios` / `parse_run_result_scenarios` / `list_screenshots` / `_fold_summary` / `_load_run_result` / `_run_result_verdict_and_bugs` / `_verdict_from_run_result` / `parse_verdict` / `parse_bugs` / `parse_filtered_failures` → `artifacts.py`
- [x] 4.2 搬移 `runs` 组：`classify_run` / `_resolve_run_file` / `_first_run_event_ts` / `get_runs` / `_read_run_lines` / `_parse_run_lines` / `get_run_events` / `read_run_events_between` / `active_run_count` / `_run_tail_insights` / `compute_run_cost` / `_split_llm_marker` / `_RUN_TERMINAL_STATUS_MAP` / `_RUN_STALE_SECONDS` → `runs.py`
- [x] 4.3 搬移 `timeline` 组：`_admin_events_for_spec` / `get_spec_timeline` / `_collapse_timeline` / `_parse_iso_ts` / `_timeline_sort_key` / `_ts_delta` / `_timeline_with_retry` / `_cost_summary_from_timeline` / `_backtrack_reason` / `_load_billing_config` / `_LIFECYCLE_ORDER` → `timeline.py`（`_run_tail_insights` **归 runs.py，不在本组**，见 4.2 与 design D3 不变量）
- [x] 4.4 搬移 `summary` 组：`daemon_health` / `hosting_state` / `project_summary` / `_spec_total_duration` / `_resolve_global_impl_run_budget` / `spec_summary` / `_stat_sig` / `_runs_by_spec_sigs` / `_spec_dep_sigs` / `SummaryIndex` / `spec_detail` / `overview` / `_degraded_project` / `_token_usage_view` / `_parse_spec_ts` / `_updated_spec_counts` / `_token_recent_entries` → `summary.py`
- [x] 4.5 搬移 `config_admin` 组：`_managed_key_sources` / `_managed_admin_keys` / `read_config` / `_config_file_sig` / `read_effective_config` / `_deep_merge_managed` / `write_config` / `sync_config_from_user` → `config_admin.py`（`write_config` 内部结构不动）
- [x] 4.6 子模块间依赖收敛为单向（叶子←中层←中枢），跨层引用改函数内延迟 import
- [x] 4.6b D8 patch 语义落地：`daemon_health`（`summary.py`）内对 `_is_running` 的调用、`config_admin.py` 内对 `USER_CONFIG_PATH` 的读取，全部改为**函数体内经门面解析**（`import core.dashboard.data as _facade` → `_facade._is_running(...)` / `_facade.USER_CONFIG_PATH`）；两个名字 MUST 仍绑定在门面，MUST NOT 只定义在子模块
- [x] 4.7 门面 re-export 本阶段全部符号；运行全量 pytest 与 import 校验，独立 commit
- [x] 4.8 patch 语义专测：`patch("core.dashboard.data._is_running", ...)` 与 `patch("core.dashboard.data.USER_CONFIG_PATH", ...)` 生效性验证（复跑 1.2b 的锁定测试 + `tests/test_config.py` 的 daemon_health 用例）。MUST NOT 以「全量 pytest 通过」代替本项——patch 静默失效可能表现为假通过

## 5. 阶段 4：包成型与旧文件删除

- [x] 5.1 删除 `core/dashboard/data/_legacy.py`（内容已全部迁入子模块或留在门面），确认门面不再有任何 `_legacy` 依赖，且 `core/dashboard/data.py` 已不存在
- [x] 5.2 逐条执行契约清单：`python -c` 访问 `core.dashboard.data` 的全部清单符号（含 `_parse_run_task_done` / `_find_impl_run_file` / `_is_running` / `USER_CONFIG_PATH` 与全部分组常量），确认无一 AttributeError
- [x] 5.3 运行 `tests/test_dashboard_data_modules_contract.py`：验证两条 import 路径、私有别名、常量可达、patch 目标仍绑定在门面、以及不存在 >1500 行子模块
- [x] 5.4 全量 pytest 全绿（相对基线无新失败），独立 commit

## 6. 阶段 5：收尾验证

- [x] 6.1 全量 `bin/run_full_suite.py`（**必须全量回归，不得只跑子集**）+ 全部 import 路径验证 + 疑点清单最终汇报（向用户汇报，代码不动）
- [x] 6.2 经用户确认时机后 `touch .fenix/restart_request` 重启 daemon 并冒烟验证（重构收尾前不得重启）

## 验证修复（原地打回第 1 轮）

- [ ] 先复核失败有效性：逐条核对 `spec/changes/refactor-dashboard-data-module/verification-report.md` 中失败场景的期望断言（状态字面量/选择器/前置数据）与产品实际行为是否相符——断言与产品不符属场景缺陷，修场景文件；确属产品行为不符才修产品代码
- [ ] 按复核结论修复：场景缺陷改场景文件，真实产品 Bug 改产品代码
- [ ] 修复后重跑验证确认通过
