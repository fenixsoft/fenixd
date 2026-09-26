"""
Contract tests for core.dashboard.data module structure.

Task 5.3 of refactor-dashboard-data-module SPEC.
验证门面 re-export 契约：
- 两条 import 路径均可用（from core.dashboard import data / from core.dashboard.data import X）
- 私有别名可访问（_parse_run_task_done / _find_impl_run_file）
- 模块级常量可达（32 个分组常量）
- patch 目标仍绑定在门面（_is_running / USER_CONFIG_PATH）
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_two_import_paths_work():
    """两条 import 路径均可用，且指向同一实现。"""
    from core.dashboard import data as d1
    from core.dashboard.data import parse_state
    assert d1.parse_state is parse_state


def test_private_aliases_accessible():
    """下划线私有别名可访问且可调用（spec 验收场景）。"""
    import core.dashboard.data as d
    assert callable(d._parse_run_task_done)
    assert callable(d._find_impl_run_file)


def test_is_running_bound_to_facade():
    """_is_running patch 目标绑定在门面且可调用。"""
    import core.dashboard.data as d
    assert callable(d._is_running)


def test_user_config_path_bound_to_facade():
    """USER_CONFIG_PATH patch 目标绑定在门面且为 Path。"""
    import core.dashboard.data as d
    assert isinstance(d.USER_CONFIG_PATH, Path)


# 32 个模块级常量（design D2 第 3 类，全部须从门面可达）
MODULE_CONSTANTS = [
    "ADMIN_INVOKE_REQUEST", "CANCEL_RUN_REQUEST", "SCHEDULING_KICK_REQUEST",
    "APPROVE_PUSH_REQUEST", "_SPEC_NAME_RE", "_SPEC_DOC_WHITELIST",
    "_LIVE_OVERLAY_STATUSES", "LOG_INDEX_BLOCK", "LOG_INDEX_TAIL_WINDOW",
    "_LOG_INDEX_REBUILDS", "_RUN_TERMINAL_STATUS_MAP", "_RUN_STALE_SECONDS",
    "_DAEMON_HEALTH_TTL", "_DAEMON_HEALTH_CACHE", "_HOSTING_STATE_TTL",
    "_HOSTING_STATE_CACHE", "_GLOBAL_BUDGET_CACHE", "_GLOBAL_BUDGET_CACHE_MAX",
    "_LIFECYCLE_ORDER", "_MANAGED_KEYS",
    "USER_CONFIG_PATH", "_SOURCE_KEYS", "_DEFAULT_SELF_REVIEW",
    "_CONFIG_HEADER_COMMENT", "_ADMIN_DEFAULTS", "_EFFECTIVE_CONFIG_CACHE",
    "_EFFECTIVE_CONFIG_CACHE_MAX", "_SYNC_PAGE_KEYS", "EVOLUTION_DOC_WHITELIST",
]


@pytest.mark.parametrize("const", MODULE_CONSTANTS)
def test_module_constants_accessible(const):
    """模块级常量全部可从门面访问。"""
    import core.dashboard.data as d
    assert hasattr(d, const), f"{const} 缺失于门面"


# 关键公开函数抽样（跨全部 13 个子模块）
KEY_FUNCTIONS = [
    # state
    "parse_state",
    # evolution_items
    "read_evolution_items", "read_evolution_analysis", "read_evolution_draft",
    # log_index
    "get_recent_events", "record_project_event",
    # tasks
    "parse_tasks", "task_progress", "tasks_note", "run_task_progress",
    # admin_alerts
    "get_alerts", "alerts_summary", "get_admin_activities",
    # spec_docs
    "resolve_spec_dir", "get_spec_doc", "count_scenarios", "count_planned_scenarios",
    # spec_archive
    "soft_delete_spec", "archive_spec", "auto_archive_check",
    # admin_actions
    "request_admin_invoke", "freeze_spec", "promote_spec", "write_config",
    # artifacts
    "parse_verify_progress", "parse_verdict", "parse_bugs",
    # runs
    "classify_run", "get_runs", "compute_run_cost",
    # timeline
    "get_spec_timeline", "_collapse_timeline",
    # summary
    "daemon_health", "hosting_state", "project_summary", "spec_summary",
    "spec_detail", "overview", "SummaryIndex",
    # config_admin
    "read_config", "read_effective_config", "sync_config_from_user",
]


@pytest.mark.parametrize("fn", KEY_FUNCTIONS)
def test_key_functions_accessible(fn):
    """跨全部分组的代表性函数可从门面访问。"""
    import core.dashboard.data as d
    assert callable(getattr(d, fn)), f"{fn} 不可调用"


def test_patch_targets_are_facade_bound():
    """patch("core.dashboard.data.X") 语义：两个名字绑定在门面。

    搬移后 daemon_health（summary.py）内经 _facade._is_running 解析、
    config_admin.py 内经 _facade.USER_CONFIG_PATH 解析，patch 门面生效。
    """
    import tempfile
    import shutil
    from unittest.mock import patch
    import core.dashboard.data as d

    tmp = tempfile.mkdtemp()
    tmp2 = tempfile.mkdtemp()
    try:
        with patch("core.dashboard.data._is_running", return_value=True):
            r1 = d.daemon_health(tmp)
        with patch("core.dashboard.data._is_running", return_value=False):
            r2 = d.daemon_health(tmp2)  # 不同 root 避开 TTL 缓存
        assert r1 == "running" and r2 == "stopped"

        user_path = Path(tmp) / "config.yaml"
        user_path.write_text("llm:\n  provider: patched-provider\n", encoding="utf-8")
        with patch("core.dashboard.data.USER_CONFIG_PATH", user_path), \
             patch("core.config.USER_CONFIG_DIR", Path(tmp)):
            result = d.read_effective_config(tmp2)
        assert result["llm"]["provider"] == "patched-provider"
    finally:
        shutil.rmtree(tmp)
        shutil.rmtree(tmp2)


def test_legacy_module_removed():
    """_legacy.py 与 data.py 均不存在。"""
    data_dir = Path(__file__).resolve().parent.parent / "core" / "dashboard" / "data"
    assert not (data_dir / "_legacy.py").exists()
    assert not (data_dir.parent / "data.py").exists()
