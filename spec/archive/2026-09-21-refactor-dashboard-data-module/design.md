# Design: refactor-dashboard-data-module

## Context

`core/dashboard/data.py` 5297 行 / 123 个顶层函数，被全仓 import 约 227 处（其中 `core/pm_engine/` 有 3 处反向依赖，属既有分层倒置，本变更**不**处理，只保持兼容）。它是近 200 提交中改动最频繁的文件（137 次），多 Agent 并发开发时冲突集中于此。项目已有一次成功的包化先例（`refactor-core-packages`：`core/pm_engine.py` → `core/pm_engine/` 包 + 门面委托），本变更复用同一模式。

约束：
- **零行为变化**，全量 pytest 不引入新失败；
- 消费点约 227 处**零修改**（含对下划线私有名的引用）；
- 重构期间 daemon 不重启（内存持旧代码），收尾重启需用户确认时机；
- 不得以绝对行号作为任务/交付锚点（本 spec 之后的其它 spec 会继续改这些文件）。

## Goals / Non-Goals

**Goals**
- 把 9 类职责拆到独立子模块，每模块职责单一、可整文件理解。
- 既有 import 路径与符号名 100% 兼容。
- 为后续巨型文件拆分（`refactor-agent-runner-module` / `refactor-verification-module`）建立可复用的门面拆分范式。

**Non-Goals**
- 不修任何 bug、不做性能优化（由 `fix-dashboard-read-path-performance` 负责）、不改行为。
- 不消除 `core/pm_engine` 的 3 处反向 import（保持现状可编译）。
- 不迁移测试（测试调用路径经门面不变）。

## Decisions

### D1：拆为 `core/dashboard/data/` 包 + 薄门面，而非新建平级模块
`data.py` 是模块名也被大量 `from core.dashboard import data` 引用。改成同名包（`data/__init__.py` 作门面）可让两条 import 路径都零改动；平级新模块则要改 227 处。选包。

### D2：门面 re-export 全量公开名 + 私有别名 + 模块级常量
`__init__.py` 除公开函数外，MUST re-export 既有私有别名与**模块级常量**，因测试与内部调用会引用。

三类别名 MUST 逐条登记，**不得只用「AST 顶层 def 扫描」**（会漏掉非 def 的绑定）：

1. **兼容别名块**（`core/dashboard/data.py:1336-1343`）：`_parse_run_task_done = parse_run_task_done`、`_find_impl_run_file = find_impl_run_file`。它们由 `from core.run_task_track import (...)` 的名字二次绑定而来，**不是** `def`，且被本包内 `run_task_progress` 调用、被 `core/run_task_track.py:91` 的文档引用，spec 的验收场景显式要求其可用 → 必须随 `tasks` 组一起迁移并保持名字。
2. **导入别名**：`_is_running`（`core/dashboard/data.py:29`，`from core.fenix_session import is_running as _is_running`）。data.py 从未定义它，却在包外被大量以 `data._is_running` 访问（`tests/test_config.py` 8 处 `patch`）。
3. **模块级常量**：`USER_CONFIG_PATH`（`data.py:3934`）等 32 个顶层赋值/别名（含 `LOG_INDEX_BLOCK`、`_LIVE_OVERLAY_STATUSES`、`_DAEMON_HEALTH_CACHE`、`_LOG_INDEX_REBUILDS`、`_MANAGED_KEYS`、`APPROVE_PUSH_REQUEST`、`EVOLUTION_DOC_WHITELIST` 等）。

规则：常量随其所属职责组迁入对应子模块；`_is_running` 与 `USER_CONFIG_PATH` 因需保持 patch 语义（见 D8）**不迁入任何子模块，保留在门面**并在需要处经门面解析。判定清单由 `grep -rn "core\.dashboard\.data\.\|data\.[A-Za-z_]"`（含 `patch("core.dashboard.data.` 目标）得出，落盘进 `contract-inventory.md` 并纳入验收。

### D3：分组边界即职责边界（交付契约）

| 新子模块 | 迁入内容（按函数名聚类） |
|---|---|
| `admin_alerts.py` | `get_alerts` / `get_unhandled_alerts` / `get_resolved_alerts` / `mark_alert_handled` / `mark_all_alerts_handled` / `alerts_summary` / `get_admin_activities` |
| `admin_actions.py` | `request_admin_invoke` / `request_run_cancel` / `freeze_spec` / `unfreeze_spec` / `is_spec_frozen` / `promote_spec` / `reflow_spec` / `re_review_spec` / `reclassify_infra_rounds` / `_write_scheduling_kick_signal` / `get_spec_start_after` / `set_spec_start_after` / `get_frozen_until` / `configure_spec_freeze` / `set_spec_budget` / `request_spec_approve_push` / `clear_spec_error` / `set_spec_priority` |
| `spec_archive.py` | `soft_delete_spec` / `archive_spec` / `is_spec_archived` / `auto_archive_check` |
| `spec_docs.py` | `resolve_spec_dir` / `InvalidSpecName` / `InvalidSpecDoc` / `InvalidPriority` / `get_spec_doc` / `_read_spec_scenarios` / `count_scenarios` / `count_generated_scenarios` / `spec_generation_progress` |
| `tasks.py` | `parse_tasks` / `task_progress` / `tasks_note` / `run_task_progress` / `_should_overlay` / `_LIVE_OVERLAY_STATUSES` / `find_implementer_worktree` / `_parse_run_task_done` / `_find_impl_run_file`（后两者为 `data.py:1336-1343` 兼容别名块，门面 MUST 同时保留绑定） |
| `log_index.py` | `_log_index_path` / `_build_log_block_index` / `_write_log_index` / `_update_log_block_index` / `_load_log_index` / `_read_log_tail_window` / `_iter_tail_log_entries` / `_norm_utc_iso` / `_read_log_window_from` / `get_recent_events` / `record_project_event` |
| `artifacts.py` | `parse_verify_progress` / `parse_report` / `parse_test_scenarios` / `parse_run_result_scenarios` / `list_screenshots` / `_fold_summary` / `_load_run_result` / `_run_result_verdict_and_bugs` / `_verdict_from_run_result` / `parse_verdict` / `parse_bugs` / `parse_filtered_failures` |
| `runs.py` | `classify_run` / `_resolve_run_file` / `_first_run_event_ts` / `get_runs` / `_read_run_lines` / `_parse_run_lines` / `get_run_events` / `read_run_events_between` / `active_run_count` / `_run_tail_insights` / `compute_run_cost` / `_split_llm_marker` |
| `summary.py` | `daemon_health` / `hosting_state` / `project_summary` / `_spec_total_duration` / `_resolve_global_impl_run_budget` / `spec_summary` / `_stat_sig` / `_runs_by_spec_sigs` / `_spec_dep_sigs` / `SummaryIndex` / `spec_detail` / `overview` / `_degraded_project` / `_token_usage_view` / `_parse_spec_ts` / `_updated_spec_counts` / `_token_recent_entries` |
| `timeline.py` | `_admin_events_for_spec` / `get_spec_timeline` / `_collapse_timeline` / `_parse_iso_ts` / `_timeline_sort_key` / `_ts_delta` / `_timeline_with_retry` / `_cost_summary_from_timeline` / `_backtrack_reason` / `_load_billing_config` |
| `config_admin.py` | `_managed_key_sources` / `_managed_admin_keys` / `read_config` / `_config_file_sig` / `read_effective_config` / `_deep_merge_managed` / `write_config` / `sync_config_from_user` |
| `evolution_items.py` | `read_evolution_items` / `read_evolution_analysis` / `read_evolution_draft` |
| `state.py` | `parse_state` |

> 具体函数→模块的最终归属以「职责自洽」为准；表的用途是定分组，不要求逐行钉死。若某函数跨组，按其主要职责归一组并在门面 re-export。
>
> **不变量（消除歧义）**：
> - `_run_tail_insights` 只归 **`runs.py`**（定义在 `data.py:3118`，与 `compute_run_cost`/`_split_llm_marker` 同处 run 成本区；`summary`/`timeline` 的调用点经跨层引用解析）。它 MUST NOT 同时出现在 `summary.py` 或 `timeline.py`。
> - 每个子模块 MUST 一并承接本组函数读取的模块级常量（见 D2 第 3 类），避免同一常量在多处重复定义造成状态分叉。
> - `_is_running` / `USER_CONFIG_PATH` 不属于任何组，留在门面（见 D2、D8）。

### D4：搬移顺序按依赖度分阶段（先叶子后中枢），每阶段独立 commit
按「被本包内其它函数引用的次数」从少到多搬：叶子组（`evolution_items` / `state` / `log_index` / `tasks`）→ 中层（`admin_alerts` / `admin_actions` / `spec_archive` / `spec_docs`）→ 中枢（`artifacts` / `runs` / `timeline` / `summary` / `config_admin`）。中枢组引用面广，最后搬以缩小过渡期。

### D5：`write_config`（约 480 行单函数）不做内部拆分
它是本包内自带段落编号（读→校验→合并→写盘）的长函数，内部拆分**改变控制流结构**、影响面大于搬移。本变更只把它整体搬入 `config_admin.py`，**内部不动**；若确需拆分另立 spec。

### D6：不使用绝对行号锚点
任务与交付物一律以**函数名 / 模块名 / import 路径**锚定。行号仅供本次起草时的定位参考，不得写入任务描述作为验收依据（后续 spec 会继续修改这些文件）。

### D7：同名包遮蔽 → 阶段 1 MUST 先「改名入包」再逐组搬移
Python 的文件查找器**先判目录（包）再判同名模块**（CPython `importlib/_bootstrap_external.py:1557-1564`，包命中即 `return`，早于同函数第 1569 行起的文件后缀扫描）。因此 `core/dashboard/data/__init__.py` 一旦存在，`core/dashboard/data.py` **立即不可达**——不会出现「新旧共存、旧文件继续服务未搬移函数」的过渡态。

后果：若按 tasks 2.1「先建空包 + 空 `__init__.py`」执行，则从阶段 1 的第一个 commit 起，尚未搬移的约 100 个函数与 32 个常量全部消失，`import core.dashboard.data` 得到空门面，全量 pytest 不可能通过，D4「每阶段独立 commit 且全绿」与回滚粒度同时失效。

因此阶段 1 的第一步 MUST 是**改名入包**：

1. `git mv core/dashboard/data.py core/dashboard/data/_legacy.py`（旧实现整体改名，**不删不改内容**）；
2. `data/__init__.py` 显式 re-export `_legacy` 的全部名（公开名 + 下划线名 + 常量，逐条 `from ._legacy import <name>`，禁用 `import *`，因它不携带下划线名）；
3. 此后每阶段从 `_legacy.py` 中**摘出**一组到新子模块，门面同步改为从新子模块 re-export 该组；
4. 阶段 4 删除 `_legacy.py`，此时门面已无 `_legacy` 依赖。

该做法与仓库既有成功先例 `spec/archive/2026-09-07-refactor-core-packages/design.md:33-58,70-85` 一致（其 `core/pm_engine.py` 同样整体改名为包内 `core/pm_engine/engine.py` 后才逐组件委托），只是本变更是模块级函数而非类方法，需多一步显式 re-export。

### D8：可 patch 全局名的语义保持（门面 re-export **不足以**保持 `mock.patch` 语义）
`unittest.mock.patch("core.dashboard.data.X")` 的语义是 `setattr(门面模块, "X", 替身)`。门面里的 `from .mod import X` 只是**一次性值拷贝**，子模块函数在调用时读的是**自己模块的全局**，因此：

- 若 `X` 是**可变对象**（dict/list/set），包外对门面的**原地操作**仍作用于同一对象 → `.clear()` / `["k"]=v` / `.append()` 依旧有效；
- 若包外**重新绑定**或 **patch 替换**该名字，则**只有门面被改，子模块不受影响**，patch 静默失效。

已确认的失效点（非推测）：

| patch 目标 | 现状位置 | 被 patch 的调用点 | 受影响测试 |
|---|---|---|---|
| `core.dashboard.data._is_running` | `data.py:29` 导入别名，仅 `daemon_health`（`data.py:2666-2686`）调用 | `daemon_health` 将迁入 `summary.py` | `tests/test_config.py` 8 处 patch（397/402/407/418/432/522/529/546）→ 变真调用真实 `is_running`，`test_running_when_is_running_true`、`test_ttl_memo_reuses_result` 等断言失败 |
| `core.dashboard.data.USER_CONFIG_PATH` | `data.py:3934` 模块级常量 | `read_effective_config` / `read_config` / `write_config` / `sync_config_from_user`（`data.py:4124,4298,4617,5100-5123`）将迁入 `config_admin.py` | `tests/test_dashboard_data.py:721,1957,2022` 的用户级配置隔离失效 → 读真实 `~/.fenix/config.yaml`，出现环境敏感假失败 |

要求：

1. 这两处**调用点 MUST 在函数体内经门面延迟解析**（如 `import core.dashboard.data as _facade` 后 `_facade._is_running(key)`、`_facade.USER_CONFIG_PATH`），与 D4/task「跨层引用改函数内延迟 import」同一机制，模块级 import 会造成循环依赖；
2. 这两个名字 MUST 保留在门面绑定，MUST NOT 只在子模块内定义；
3. 门面 MUST NOT 使用 `import *`（无法携带下划线名），逐条显式 re-export。

## Risks / Trade-offs

- [门面遗漏某个私有名 → 消费点 AttributeError] → 验收项显式包含 `python -c "import core.dashboard.data as d; ..."` 逐一访问清单（含 `_parse_run_task_done` / `_find_impl_run_file` / `_is_running` / `USER_CONFIG_PATH` 及 32 个模块级常量）+ 全量 pytest。
- [循环 import：子模块互相引用] → 子模块间只允许单向依赖（叶子←中层←中枢），跨层引用在函数内延迟 import；包门面最后导入。
- [测试以 `data` 模块为 patch 目标 → mock 静默失效] → 门面 re-export **不**能保持 `mock.patch` 语义（详见 D8 的两处已确认失效点）；`_is_running` / `USER_CONFIG_PATH` 的调用点改经门面延迟解析，并在阶段 4 用「patch 后断言 patch 生效」的专测验证，不得只以「全量 pytest 通过」代替（patch 失效可能表现为假通过或环境敏感失败）。
- [建包即遮蔽旧模块 → 中间态全红] → 阶段 1 先 `git mv` 改名入包再逐组摘出（D7），MUST NOT 先建空包。
- [与其它在飞变更冲突] → 本 spec 与 performance/observability 等做成串行依赖，由调度顺序保证不并发。

## Migration Plan

1. 阶段 0：补 characterization tests（含 D8 两处 patch 目标的锁定测试）+ 契约清单 + 疑点清单。
2. 阶段 1：先 `git mv core/dashboard/data.py core/dashboard/data/_legacy.py` + 门面逐条 re-export（D7），再摘出叶子组；此后阶段 2–3 按 D4 分组从中枢外向内搬移，每阶段全量 pytest + import 校验 + 独立 commit。
3. 阶段 4：删除 `core/dashboard/data/_legacy.py`，包成型，逐一验证 import 路径与符号（含常量与 patch 语义）。
4. 阶段 5：收尾——全量 pytest、疑点清单汇报；**daemon 重启经用户确认时机后**执行并冒烟。

**回滚**：每阶段独立 commit，任一阶段失败可回退该 commit，前序阶段成果保留。
