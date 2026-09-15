"""core.dashboard.data — 门面（facade）re-export。

按 design D1/D2/D7：data.py 拆分为 data/ 包，本模块作为薄门面逐条 re-export
全部既有名字，保证既有调用路径零改动。

_D8 约定_：`_is_running` 与 `USER_CONFIG_PATH` 两个可 patch 名保留在本门面
绑定；被搬移函数内对它们的访问 MUST 经本门面延迟解析（见 D8）。
"""

import copy
import json
import os
import re
import shutil
import tempfile
import threading
import time
from collections import deque
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

from core.agent_runner.run_files import (archive_spec_runs,
                                         infer_run_agent_type, run_spec_part)
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
    request_admin_invoke,
    request_run_cancel,
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
    set_spec_budget,
    configure_spec_freeze,
    request_spec_approve_push,
    clear_spec_error,
    set_spec_priority,
)

# ── spec_archive 组 ──
from .spec_archive import (
    soft_delete_spec,
    archive_spec,
    is_spec_archived,
    auto_archive_check,
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

# ── state 组 ──
from .state import parse_state

# ── config_admin 组 ──
from .config_admin import (
    _MANAGED_KEYS,
    _AGENTS_MANAGED_SUBKEYS,
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
)
