"""core.dashboard.data — 门面（facade）re-export。

按 design D1/D2/D7：data.py 拆分为 data/ 包，本模块作为薄门面逐条 re-export
全部既有名字，保证既有调用路径零改动。

_D8 约定_（可 patch 名契约，code-review item 895133450e96 修正：原文档只列了
`_is_running` 与 `USER_CONFIG_PATH`，范围过窄，实际远不止这两个）：被搬移函数内
通过**本门面**（`import core.dashboard.data as _facade` 后 `_facade.<name>`）
延迟解析的全部名字都构成 patch 缝，测试以 `patch.object(core.dashboard.data,
"<name>")` 打桩。当前已知清单（新增门面延迟引用时同步登记）：

    _is_running, USER_CONFIG_PATH,
    archive_spec_runs   (spec_archive.py:201，显式 D8 注释),
    spec_summary        (summary.py:585),
    parse_verify_progress (spec_docs.py:191),
    classify_run        (tasks.py:206),
    parse_quality_gates (quality_gates.py，summary.py 经门面消费),
    find_implementer_worktree (tasks.py，quality_gates.py 经门面解析),
    _resolve_run_file, _read_run_lines (runs.py，quality_gates.py 经门面解析),
    read_run_lines      (runs.py，tasks.py 经门面解析；code-review 09c363a0b1b9)

MUST NOT 把这些 `_facade.X` 访问「整理」成直接 import——会静默破坏
monkeypatch 语义（对应测试会以难定位的方式失败）。
"""

# stdlib 绑定：纯兼容 re-export 面（code-review item a605cfddb10f）。仓内唯一被
# 外部访问的是门面命名空间下的 ``yaml``（tests/test_dashboard_index.py）；
# ``os``/``re``/``threading`` 等在本包内无引用点，保留仅为路径兼容。与同包
# 兄弟模块（admin_actions.py:33 / artifacts.py:19 / tasks.py:47）同款加
# ``# noqa: F401``，使「保留供兼容、非本处使用」的意图对 linter 可见。
import copy  # noqa: F401
import json  # noqa: F401
import os  # noqa: F401
import re  # noqa: F401
import shutil  # noqa: F401
import tempfile  # noqa: F401
import threading  # noqa: F401
import time  # noqa: F401
from collections import deque  # noqa: F401
from datetime import datetime, timezone, timedelta  # noqa: F401
from pathlib import Path  # noqa: F401

import yaml  # noqa: F401

from core.agent_runner.run_files import archive_spec_runs
from core.archive_commit import commit_archive_move
from core.fenix_session import is_running as _is_running
from core.state_machine import (
    FREEZE_ERROR_PREFIX,
    FROZEN_FIELD,
    parse_orig_status,
    INFRA_FAILURE_COUNT_FIELD,
    VERIFY_INFRA_ROUNDS_FIELD,
)

# D8：USER_CONFIG_PATH 门面绑定（config_admin 组内经 _facade.USER_CONFIG_PATH 解析）
USER_CONFIG_PATH = Path.home() / ".fenix" / "config.yaml"


# ── summary 组 ──
from .summary import (
    _DAEMON_HEALTH_TTL,
    _DAEMON_HEALTH_CACHE,
    daemon_health,
    _HOSTING_STATE_TTL,
    _HOSTING_STATE_CACHE,
    hosting_state,
    project_summary,
    _spec_total_duration,
    _GLOBAL_BUDGET_CACHE,
    _GLOBAL_BUDGET_CACHE_MAX,
    _resolve_global_impl_run_budget,
    spec_summary,
    _stat_sig,
    _runs_by_spec_sigs,
    _spec_dep_sigs,
    SummaryIndex,
    spec_detail,
    _token_usage_view,
    _parse_spec_ts,
    _updated_spec_counts,
    _token_recent_entries,
    _degraded_project,
    _cached_config_value,
    overview,
)

# ── timeline 组 ──
from .timeline import (
    _LIFECYCLE_ORDER,
    _backtrack_reason,
    _load_billing_config,
    _admin_events_for_spec,
    get_spec_timeline,
    _collapse_timeline,
    _parse_iso_ts,
    _timeline_sort_key,
    _ts_delta,
    _timeline_with_retry,
    _cost_summary_from_timeline,
)

# ── runs 组 ──
from .runs import (
    classify_run,
    _resolve_run_file,
    _first_run_event_ts,
    get_runs,
    _read_run_lines,
    read_run_lines,
    _parse_run_lines,
    get_run_events,
    read_run_events_between,
    active_run_count,
    _run_tail_insights,
    compute_run_cost,
    _split_llm_marker,
    _RUN_TERMINAL_STATUS_MAP,
    _RUN_STALE_SECONDS,
    run_activity,
    runs_retention_check,
)

# ── artifacts 组 ──
from .artifacts import (
    parse_verify_progress,
    parse_report,
    parse_test_scenarios,
    parse_run_result_scenarios,
    list_screenshots,
    _fold_summary,
    _load_run_result,
    _run_result_verdict_and_bugs,
    _verdict_from_run_result,
    parse_verdict,
    parse_bugs,
    parse_filtered_failures,
)

# ── admin_actions 组 ──
from .admin_actions import (
    ADMIN_INVOKE_REQUEST,
    CANCEL_RUN_REQUEST,
    SCHEDULING_KICK_REQUEST,
    APPROVE_PUSH_REQUEST,
    SPEC_DELETE_REQUEST,
    request_admin_invoke,
    request_run_cancel,
    request_spec_delete,
    running_run_ids_for_spec,
    is_spec_frozen,
    freeze_spec,
    unfreeze_spec,
    reclassify_infra_rounds,
    promote_spec,
    reflow_spec,
    re_review_spec,
    _write_scheduling_kick_signal,
    get_spec_start_after,
    get_frozen_until,
    set_spec_start_after,
    activate_spec,
    resume_cancelled_spec,
    set_spec_budget,
    configure_spec_freeze,
    request_spec_approve_push,
    clear_spec_error,
    set_spec_priority,
    # 裁决动词与 choice 映射执行器（add-human-adjudication-choices 3.x/4.x）
    reset_verification,
    force_advance,
    skip_review_gate,
    execute_adjudication_choice,
)

# fix-scheduling-kick-single-slot D2：SCHEDULING_KICK_DIR / write_scheduling_kick
# 来自 core.signals（中性模块），daemon 与 dashboard 双端共用同一份定义。
# validate_scheduling_kick_spec 直接从 core.signals 导入（非经 admin_actions 中转）。
from core.signals import (  # noqa: F401
    SCHEDULING_KICK_DIR,
    write_scheduling_kick,
    validate_scheduling_kick_spec,
)

# ── spec_archive 组 ──
from .spec_archive import (
    soft_delete_spec,
    archive_spec,
    is_spec_archived,
    auto_archive_check,
    backfill_archived_entries,
)

# ── spec_docs 组 ──
from .spec_docs import (
    _SPEC_NAME_RE,
    _SPEC_DOC_WHITELIST,
    resolve_spec_dir,
    InvalidSpecName,
    InvalidSpecDoc,
    InvalidPriority,
    get_spec_doc,
    _read_spec_scenarios,
    count_scenarios,
    count_generated_scenarios,
    count_planned_scenarios,
    spec_generation_progress,
)

# ── admin_alerts 组 ──
from .admin_alerts import (
    get_alerts,
    get_unhandled_alerts,
    get_resolved_alerts,
    mark_alert_handled,
    mark_all_alerts_handled,
    alerts_summary,
    get_admin_activities,
    get_archived_activities,
)

# ── tasks 组 ──
from .tasks import (
    find_implementer_worktree,
    find_impl_run_file,
    parse_run_task_done,
    _parse_run_task_done,
    _find_impl_run_file,
    _LIVE_OVERLAY_STATUSES,
    _should_overlay,
    parse_tasks,
    task_progress,
    tasks_note,
    run_task_progress,
)

# ── log_index 组 ──
from .log_index import (
    LOG_INDEX_BLOCK,
    LOG_INDEX_TAIL_WINDOW,
    _LOG_INDEX_REBUILDS,
    _log_index_path,
    _build_log_block_index,
    _write_log_index,
    _update_log_block_index,
    _load_log_index,
    _read_log_tail_window,
    _iter_tail_log_entries,
    _norm_utc_iso,
    _read_log_window_from,
    get_recent_events,
    record_project_event,
)

# ── evolution_items 组 ──
from .evolution_items import (
    EVOLUTION_DOC_WHITELIST,
    read_evolution_items,
    read_evolution_analysis,
    read_evolution_draft,
)

# ── code_review 组（add-code-review-agent-and-quality-tab）──
from .code_review import (
    read_code_review_items,
    read_code_review_progress,
    read_code_review_fix_progress,
    read_code_review_request_result,
    read_code_fix_request_result,
)

# ── quality_gates 组（add-quality-gates-visibility）──
from .quality_gates import (
    RUN_GATE_IDS,
    GATE_STATUSES,
    GATE_ORDER,
    GATE_DESCS,
    DELIVERABLE_BLOCKED_KEYWORDS,
    current_lane_fingerprint,
    parse_quality_gates,
)

# ── regression 组（add-test-regression-tab）──
from .regression import (
    read_regression_result,
    is_regression_running,
)

# ── adjudication_choices 组（add-human-adjudication-choices）──
# 裁决选项静态注册表：发射点（choices_for 快照）、前端渲染与 alert-resolve
# 端点三处共用的事实源（design D1）。
from .adjudication_choices import (
    ADJUDICATION_CHOICES,
    SIGNAL_CHANNEL_SIGNAL_TYPES,
    choices_for,
    is_adjudicable,
    registered_signal_types,
)

# ── state 组 ──
from .state import parse_state, parse_archived_state, STATE_ARCHIVE_BASENAME

# ── config_admin 组 ──
from .config_admin import (
    _MANAGED_KEYS,
    _SOURCE_KEYS,
    _DEFAULT_SELF_REVIEW,
    _CONFIG_HEADER_COMMENT,
    _managed_key_sources,
    _ADMIN_DEFAULTS,
    _managed_admin_keys,
    read_config,
    _EFFECTIVE_CONFIG_CACHE,
    _EFFECTIVE_CONFIG_CACHE_MAX,
    _config_file_sig,
    read_effective_config,
    _deep_merge_managed,
    write_config,
    _SYNC_PAGE_KEYS,
    sync_config_from_user,
    clear_project_page_keys,
)
