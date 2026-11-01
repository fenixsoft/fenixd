"""fix-robustness-edge-cases 1.3：spec 名互为前缀的 run 流归属全等匹配。

构造 ``impl-fix-x-*`` 与 ``impl-fix-x-y-*`` 断言各「按 spec 名查 run 流」判定点
不误归属（fix-x 不得命中 fix-x-y 的产物）；并覆盖后缀形态
``impl-fix-x-<ts>-a1.jsonl`` 与 ``impl-fix-x-<ts>-a1-r2.jsonl``——断言仍归属
fix-x（全等守卫「加守卫不漏命中」，-r<n> 漏剥会把在跑 run 判成非本 spec）。

覆盖判定点（tasks 1.1 清单 + 纳入的子串 glob 点）：
  1. run_spec_part（core/agent_runner/run_files.py）
  2. budget._budget_reconcile_has_exemption（archive 目录）
  3. budget._count_normal_completed_impl_runs
  4. engine._spec_has_recent_run_activity
  5. verification/judge_gate._last_planner_run_cost（planner-plan）
  6. liveness._stream_recent
  7. worktree_manager._latest_stream_mtime
  8. run_task_track.find_impl_run_file / parse_run_task_done_cumulative
  9. dashboard/data/spec_archive.soft_delete_spec（原子串 glob，本 SPEC 纳入）
"""

import json
import shutil
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_agent_runner import FakeLogger  # noqa: E402

TS = "1789000000"


def _mk_project(tmp_path) -> Path:
    proot = Path(tmp_path) / "proj"
    (proot / ".fenix" / "runs").mkdir(parents=True)
    return proot


def _write_run(runs_dir: Path, name: str, tail: str = "system") -> Path:
    """在 runs 根目录写一个 run 产物文件：首行 init 事件 + 末行事件（缺省 system
    非终态事件——fix-orphan-ready-recovery-liveness 3.9：liveness._stream_recent
    的流新鲜度回退已排除末行终态的文件，夹具若默认写 result 终态会让
    ``_stream_recent(...) is True`` 的断言必红；system 口径与
    tests/test_run_lifecycle_governance.py::touch_run_stream 一致）。"""
    p = runs_dir / f"{name}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"type": "init", "timestamp": "2026-01-01T00:00:00Z"})
        + "\n"
        + json.dumps({"type": tail, "timestamp": "2026-01-01T00:00:01Z"})
        + "\n",
        encoding="utf-8",
    )
    return p


def _mk_engine(project_root, logger):
    from core.pm_engine import PMEngine
    from core.state_machine import StateMachine

    sm = StateMachine(project_root / ".fenix" / "STATE.md", logger)
    engine = PMEngine(sm, MagicMock(), {}, project_root, logger)
    engine.handle_event = MagicMock()
    return engine, sm


def _make_pm(project_root):
    from core.state_machine import StateMachine

    sm = StateMachine(project_root / ".fenix" / "STATE.md", _FakeLogger())
    pm = MagicMock()
    pm.project_root = project_root
    pm.logger = _FakeLogger()
    pm.state_machine = sm
    return pm, sm


class _FakeLogger:
    def debug(self, *a, **kw):
        pass

    def info(self, *a, **kw):
        pass

    def warning(self, *a, **kw):
        pass

    def error(self, *a, **kw):
        pass


class _FakePM:
    """liveness 的 _pm 最小实现。"""

    def __init__(self, project_root):
        self.project_root = project_root
        self._running_agents = {}
        self.logger = MagicMock()

    def _parse_event_timestamp(self, entry):
        return entry.get("timestamp")


def _make_wm(root: Path):
    from core.worktree_manager import WorktreeManager

    base = root / ".claude" / "worktrees"
    base.mkdir(parents=True, exist_ok=True)
    return WorktreeManager(base, root, FakeLogger())


# ── 1. run_spec_part 解析器本身 ────────────────────────────────────


class TestRunSpecPart:
    def test_prefix_misattribution_parses_correctly(self):
        from core.agent_runner.run_files import run_spec_part

        assert run_spec_part(f"impl-fix-x-{TS}") == "fix-x"
        assert run_spec_part(f"impl-fix-x-y-{TS}") == "fix-x-y"
        # 前缀命中（fix-x 命中 fix-x-y 的文件）经解析后不得归属 fix-x
        assert run_spec_part(f"impl-fix-x-y-{TS}") != "fix-x"

    def test_suffix_forms_still_parse(self):
        from core.agent_runner.run_files import run_spec_part

        assert run_spec_part(f"impl-fix-x-{TS}-a1") == "fix-x"
        assert run_spec_part(f"impl-fix-x-{TS}-a1-r2") == "fix-x"
        assert run_spec_part(f"impl-fix-x-{TS}-r1") == "fix-x"


# ── 2/3. budget 判定点 ─────────────────────────────────────────────


class TestBudgetAttribution:
    def _engine(self, tmp_path):
        proot = _mk_project(tmp_path)
        logger = MagicMock()
        engine, _sm = _mk_engine(proot, logger)
        return proot, engine

    def test_reconcile_exemption_archive_excludes_prefix_other_spec(self, tmp_path):
        """archive/ 只有 fix-x-y 的产物 → fix-x 不豁免（原 glob 会误豁免）。"""
        proot, engine = self._engine(tmp_path)
        arc = proot / ".fenix" / "runs" / "archive"
        arc.mkdir(parents=True)
        _write_run(arc, f"impl-fix-x-y-{TS}")
        assert engine._budget._budget_reconcile_has_exemption("fix-x") is False
        assert engine._budget._budget_reconcile_has_exemption("fix-x-y") is True

    def test_reconcile_exemption_archive_includes_own_with_suffix(self, tmp_path):
        """archive/ 有 fix-x 的 -a1-r2 产物 → fix-x 仍豁免（不漏命中）。"""
        proot, engine = self._engine(tmp_path)
        arc = proot / ".fenix" / "runs" / "archive"
        arc.mkdir(parents=True)
        _write_run(arc, f"impl-fix-x-{TS}-a1-r2")
        assert engine._budget._budget_reconcile_has_exemption("fix-x") is True

    def test_count_normal_completed_excludes_prefix_other_spec(self, tmp_path):
        """fix-x-y 的正常收工文件不得计入 fix-x 的收工数。"""
        proot, engine = self._engine(tmp_path)
        _write_run(proot / ".fenix" / "runs", f"impl-fix-x-y-{TS}")
        assert engine._budget._count_normal_completed_impl_runs("fix-x") == 0
        _write_run(proot / ".fenix" / "runs", f"impl-fix-x-{TS}")
        assert engine._budget._count_normal_completed_impl_runs("fix-x") == 1

    def test_count_normal_completed_groups_retry_suffix(self, tmp_path):
        """-a1 与 -a1-r2 属同一 run：重试文件（最新）计入一次，不双计。"""
        proot, engine = self._engine(tmp_path)
        p_a1 = _write_run(proot / ".fenix" / "runs", f"impl-fix-x-{TS}-a1")
        _write_run(proot / ".fenix" / "runs", f"impl-fix-x-{TS}-a1-r2")
        # 让 -a1-r2 成为最新文件（先写 -a1 再写重试文件，mtime 天然更新）
        assert p_a1.exists()
        assert engine._budget._count_normal_completed_impl_runs("fix-x") == 1


# ── 4. engine._spec_has_recent_run_activity ────────────────────────


class TestEngineRecentRunActivity:
    def test_prefix_other_spec_activity_not_counted(self, tmp_path):
        proot = _mk_project(tmp_path)
        engine, _ = _mk_engine(proot, MagicMock())
        _write_run(proot / ".fenix" / "runs", f"impl-fix-x-y-{TS}")
        assert engine._spec_has_recent_run_activity("fix-x", 60) is False
        assert engine._spec_has_recent_run_activity("fix-x-y", 60) is True

    def test_own_activity_with_retry_suffix_counts(self, tmp_path):
        proot = _mk_project(tmp_path)
        engine, _ = _mk_engine(proot, MagicMock())
        _write_run(proot / ".fenix" / "runs", f"impl-fix-x-{TS}-a1-r2")
        assert engine._spec_has_recent_run_activity("fix-x", 60) is True


# ── 5. judge_gate._last_planner_run_cost（planner-plan 耗时点）─────


class TestPlannerCostAttribution:
    def test_prefix_other_spec_planner_not_taken(self, tmp_path):
        proot = _mk_project(tmp_path)
        pm, _sm = _make_pm(proot)
        pm.add_spec = MagicMock()
        from core.pm_engine.verification import VerificationPipeline

        runs_dir = proot / ".fenix" / "runs"
        (runs_dir / f"planner-plan-fix-x-y-{TS}.jsonl").write_text(
            json.dumps({"type": "result", "duration_ms": 500000}) + "\n",
            encoding="utf-8",
        )
        vpipe = VerificationPipeline(pm)
        assert vpipe._last_planner_run_cost("fix-x") == ""
        (runs_dir / f"planner-plan-fix-x-{TS}.jsonl").write_text(
            json.dumps({"type": "result", "duration_ms": 3600000}) + "\n",
            encoding="utf-8",
        )
        assert "1.0 小时" in vpipe._last_planner_run_cost("fix-x")


# ── 6. liveness._stream_recent ─────────────────────────────────────


class TestLivenessStreamRecent:
    def test_prefix_other_spec_stream_not_recent(self, tmp_path):
        proot = _mk_project(tmp_path)
        from core.agent_runner.liveness import LivenessSupervisor

        sup = LivenessSupervisor(_FakePM(proot))
        _write_run(proot / ".fenix" / "runs", f"impl-fix-x-y-{TS}")
        assert sup._stream_recent("fix-x", 600) is False
        assert sup._stream_recent("fix-x-y", 600) is True

    def test_own_stream_with_retry_suffix_recent(self, tmp_path):
        proot = _mk_project(tmp_path)
        from core.agent_runner.liveness import LivenessSupervisor

        sup = LivenessSupervisor(_FakePM(proot))
        _write_run(proot / ".fenix" / "runs", f"impl-fix-x-{TS}-a1-r2")
        assert sup._stream_recent("fix-x", 600) is True


# ── 7. worktree_manager._latest_stream_mtime ───────────────────────


class TestWorktreeLatestStream:
    def test_prefix_other_spec_stream_not_latest(self, tmp_path):
        proot = _mk_project(tmp_path)
        wm = _make_wm(proot)
        _write_run(proot / ".fenix" / "runs", f"impl-fix-x-y-{TS}")
        assert wm._latest_stream_mtime("fix-x") is None
        assert wm._latest_stream_mtime("fix-x-y") is not None

    def test_own_stream_with_retry_suffix_latest(self, tmp_path):
        proot = _mk_project(tmp_path)
        wm = _make_wm(proot)
        _write_run(proot / ".fenix" / "runs", f"impl-fix-x-{TS}-a1-r2")
        assert wm._latest_stream_mtime("fix-x") is not None


# ── 8. run_task_track 判定点 ───────────────────────────────────────


class TestRunTaskTrack:
    def test_find_impl_run_file_excludes_prefix_other_spec(self, tmp_path):
        proot = _mk_project(tmp_path)
        from core.run_task_track import find_impl_run_file

        _write_run(proot / ".fenix" / "runs", f"impl-fix-x-y-{TS}")
        assert find_impl_run_file(proot, "fix-x") is None
        own = _write_run(proot / ".fenix" / "runs", f"impl-fix-x-{TS}")
        assert find_impl_run_file(proot, "fix-x") == own

    def test_find_impl_run_file_accepts_retry_suffix(self, tmp_path):
        proot = _mk_project(tmp_path)
        from core.run_task_track import find_impl_run_file

        own = _write_run(proot / ".fenix" / "runs", f"impl-fix-x-{TS}-a1-r2")
        assert find_impl_run_file(proot, "fix-x") == own

    def test_parse_run_task_done_cumulative_excludes_prefix_other_spec(self, tmp_path):
        proot = _mk_project(tmp_path)
        from core.run_task_track import parse_run_task_done_cumulative

        _write_run(proot / ".fenix" / "runs", f"impl-fix-x-y-{TS}")
        res = parse_run_task_done_cumulative(proot, "fix-x")
        assert res["done_ids"] == set()
        assert res["tracked_ids"] == set()


# ── 9. soft_delete_spec 运行中保护（原子串 glob，本 SPEC 纳入）─────


class TestSoftDeleteRunningProtection:
    def test_prefix_other_spec_running_not_block(self, tmp_path):
        """fix-x-y 有进行中的 run → fix-x 的 soft_delete 不得被误拦（原子串
        glob ``*fix-x*`` 会命中 impl-fix-x-y-* 而误报 running）。"""
        proot = _mk_project(tmp_path)
        from core.dashboard.data.spec_archive import soft_delete_spec
        from core.state_machine import StateMachine

        sm = StateMachine(proot / ".fenix" / "STATE.md", _FakeLogger())
        sm.add_spec("fix-x", {"priority": 1})
        sm.add_spec("fix-x-y", {"priority": 1})
        _write_run(proot / ".fenix" / "runs", f"impl-fix-x-y-{TS}")
        # fix-x-y 在跑（mtime 新）→ 只拦 fix-x-y 自己，不拦 fix-x
        res = soft_delete_spec(proot, "fix-x")
        assert res.get("running") is not True
        res_y = soft_delete_spec(proot, "fix-x-y")
        assert res_y.get("running") is True

    def test_own_running_still_blocks(self, tmp_path):
        proot = _mk_project(tmp_path)
        from core.dashboard.data.spec_archive import soft_delete_spec
        from core.state_machine import StateMachine

        sm = StateMachine(proot / ".fenix" / "STATE.md", _FakeLogger())
        sm.add_spec("fix-x", {"priority": 1})
        _write_run(proot / ".fenix" / "runs", f"impl-fix-x-{TS}-a1-r2")
        res = soft_delete_spec(proot, "fix-x")
        assert res.get("running") is True


# ── 9. add-distill-run-artifacts 2.2：knowledge-distiller- 前缀边界 ────


DISTILL_RUN_ID = "knowledge-distiller-2026-10-31-demo-spec-1789000000"


class TestKnowledgeDistillerPrefix:
    """add-distill-run-artifacts 2.2：前缀归属正确 + 消费面边界两侧锁定。

    - 归属侧：infer_run_agent_type / run_spec_part 对蒸馏产物自动归属；
    - 边界侧：admin_monitor 失败计数不还原、pm_engine 归属不误命中、
      aggregate_org 归档剔除不吞蒸馏 run（形态错位耦合锁定）。
    """

    def test_infer_agent_type_attribution(self):
        from core.agent_runner.run_files import infer_run_agent_type

        agent, rest = infer_run_agent_type(DISTILL_RUN_ID)
        assert agent == "knowledge-distiller"
        assert rest == "2026-10-31-demo-spec-1789000000"

    def test_run_spec_part_strips_prefix_and_ts(self):
        from core.agent_runner.run_files import run_spec_part

        # 剥前缀 + 时间戳段 → 带日期前缀的归档目录名（原始 SPEC 名为
        # demo-spec，剥离结果含日期前缀 ≠ 原始名——全等守卫天然不命中）
        assert run_spec_part(DISTILL_RUN_ID) == "2026-10-31-demo-spec"

    def test_admin_monitor_does_not_restore_failure_to_spec(self):
        """admin_monitor._RUN_PREFIXES 不收录该前缀：error 终态蒸馏产物不
        还原到活跃 spec 失败计数（同 evo-/review- 口径，spec 已归档无可还原）。"""
        from core.admin_monitor import AdminMonitor, _RUN_PREFIXES

        assert "knowledge-distiller-" not in _RUN_PREFIXES
        # 失败还原判定点显式传 _RUN_PREFIXES 子集 → 蒸馏 run_id 还原不出 spec
        assert AdminMonitor._spec_from_run_id(DISTILL_RUN_ID, _RUN_PREFIXES) is None
        # 默认全量前缀真源可剥段（归属与计数口径分离的既有语义）
        assert AdminMonitor._spec_from_run_id(DISTILL_RUN_ID) == "2026-10-31-demo-spec"

    def test_pm_engine_attribution_no_misattribution(self, tmp_path):
        """伪造活跃 spec 与蒸馏 run_id 同名单（demo-spec 出现在 run_id 中段）：
        pm_engine 归属判定按 run_spec_part 全等匹配——蒸馏 run 的 spec 段为
        带日期前缀归档目录名，对活跃 spec「demo-spec」不命中。"""
        proot = _mk_project(tmp_path)
        engine, _ = _mk_engine(proot, MagicMock())
        _write_run(proot / ".fenix" / "runs", DISTILL_RUN_ID)
        assert engine._spec_has_recent_run_activity("demo-spec", 60) is False
        # 正向对照：归属机制本身工作——按剥段结果（归档目录名）可命中
        assert engine._spec_has_recent_run_activity("2026-10-31-demo-spec", 60) is True

    def test_aggregate_org_archive_filter_not_hit(self, tmp_path, monkeypatch):
        """归档剔除过滤不吞蒸馏 run（design D3 形态错位耦合锁定）：

        STATE.archive.md 清单键=原始 SPEC 名（demo-spec，无日期前缀）；
        蒸馏 run 的 spec 段=归档目录名（2026-10-31-demo-spec）。剔除按清单键
        全等匹配，形态错位不命中 → 运营线蒸馏卡 runs>=1。run_id 中段若改用
        原始 SPEC 名，剥段结果与清单键全等 → 全部蒸馏 run 被静默吞掉，本测试即红。
        """
        import os
        import time
        from datetime import datetime, timezone

        # 用户级配置隔离（成本读路径不触宿主 ~/.fenix）
        user_dir = tmp_path / "user-config"
        user_dir.mkdir()
        monkeypatch.setattr("core.config.USER_CONFIG_DIR", user_dir)
        import core.dashboard.data as dd

        monkeypatch.setattr(dd, "USER_CONFIG_PATH", user_dir / "config.yaml")

        proot = _mk_project(tmp_path)
        # 清单含首归档 SPEC 原始名（2026-10-31 已归档 demo-spec）
        (proot / ".fenix" / "STATE.archive.md").write_text(
            "# Fenix Archive State\n\n## Specs\n"
            "\n### demo-spec\n- status: pushed\n- priority: 1\n"
            "- created: 2026-10-30T00:00:00+00:00\n"
            "- updated: 2026-10-31T00:00:00+00:00\n",
            encoding="utf-8",
        )
        # done 终态蒸馏产物（mtime/started 钉当下，任意窗口均入窗）
        now = int(time.time())
        started = (
            datetime.fromtimestamp(now - 600, tz=timezone.utc).isoformat()
        )
        rid = f"knowledge-distiller-2026-10-31-demo-spec-{now - 600}"
        p = proot / ".fenix" / "runs" / f"{rid}.jsonl"
        p.write_text(
            json.dumps({"type": "started", "timestamp": started}) + "\n"
            + json.dumps({"type": "result", "result": "ok"}) + "\n",
            encoding="utf-8",
        )
        os.utime(p, (now, now))
        from core.dashboard.data import command_center as cc

        data = cc.aggregate_org(
            [{"name": "proj", "path": str(proot), "exists": True}], window="all"
        )
        cards = [
            c
            for z in data["zones"]
            for c in z["cards"]
            if c["lane"] == "knowledge-distiller"
        ]
        assert len(cards) == 1
        assert cards[0]["runs"] >= 1
        # 形态错位耦合的直接陈述：剥段结果（归档目录名）≠ 清单键（原始名）
        from core.agent_runner.run_files import run_spec_part

        assert run_spec_part(rid) != "demo-spec"
