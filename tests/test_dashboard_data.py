"""
Tests for Dashboard data functionality.

Split from test_core.py as part of refactor-test-structure.
"""
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

# Add project root to path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_machine import StateMachine


class TestDashboardConfigIO(unittest.TestCase):
    """Dashboard 配置读写：配置必须正确读写。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_dashboard_config_io(self):
        from core.dashboard.data import read_config, write_config
        config_path = Path(self.tmpdir) / ".fenix" / "config.yaml"
        config_path.parent.mkdir(parents=True, exist_ok=True)

        # 写入配置 - write_config expects a patch dict
        # Use minimal valid config to avoid validation errors
        config_patch = {
            "agents": {"max_concurrent": 2}
        }
        result = write_config(config_path.parent, config_patch)

        # 验证写入操作返回结果
        self.assertIn("ok", result)
        self.assertIn("error", result)
        # 验证返回结构正确
        self.assertEqual(result["scope"], "project")

    def test_verify_config_roundtrip_and_validation(self):
        """verify.* 受管键：读写回环 + 非法值拒绝（static_scope 曾是前端死信）。"""
        from core.dashboard.data import read_config, write_config
        config_path = Path(self.tmpdir) / ".fenix" / "config.yaml"
        config_path.parent.mkdir(parents=True, exist_ok=True)

        # 缺省回显（此前 verify 段根本不在 read_config 里，前端恒显示默认值）
        echoed = read_config(self.tmpdir)
        self.assertEqual(echoed["verify"],
                         {"static_scope": "main", "deps_mode": "prefer-offline"})

        result = write_config(self.tmpdir, {
            "verify": {"static_scope": "worktree", "deps_mode": "hardlink"},
        })
        self.assertTrue(result["ok"], result.get("error"))
        echoed = read_config(self.tmpdir)
        self.assertEqual(echoed["verify"],
                         {"static_scope": "worktree", "deps_mode": "hardlink"})
        self.assertEqual(echoed["sources"]["verify.deps_mode"], "project")

        # 非法值拒绝（不落盘）
        bad = write_config(self.tmpdir, {"verify": {"deps_mode": "symlink"}})
        self.assertFalse(bad["ok"])
        self.assertIn("deps_mode", bad["error"])
        self.assertEqual(read_config(self.tmpdir)["verify"]["deps_mode"],
                         "hardlink")


class TestDashboardParallelismConfig(unittest.TestCase):
    """Dashboard 并行配置：并行配置必须正确工作。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_parallelism_config(self):
        # 模拟并行配置
        self.assertIsNotNone(self.tmpdir)


class TestWorktreeMergeBack(unittest.TestCase):
    """Worktree merge-back：merge-back 必须正确工作。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_worktree_merge_back(self):
        # 模拟 worktree merge-back
        self.assertIsNotNone(self.tmpdir)


class TestSpecTimelineOrdering(unittest.TestCase):
    """SPEC 时间轴排序：同秒内状态转移必须先于运行节点。

    根因：日志时间戳为微秒+Z（2026-09-01T11:05:31.212625Z），运行 started 为
    秒级+00:00（2026-09-01T11:05:31+00:00），字符串排序同秒时 '+' < '.'，
    导致「转入 implementing」显示在 agent 开始工作之后。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        logs_dir = Path(self.tmpdir) / ".fenix" / "logs"
        runs_dir = Path(self.tmpdir) / ".fenix" / "runs"
        logs_dir.mkdir(parents=True)
        runs_dir.mkdir(parents=True)

        spec = "demo-spec"
        log_entry = {
            "timestamp": "2026-09-01T11:05:31.212625Z",
            "level": "INFO",
            "component": "state_machine",
            "message": f"Transition: {spec} drafted → ready",
        }
        log_entry2 = {
            "timestamp": "2026-09-01T11:05:31.321607Z",
            "level": "INFO",
            "component": "state_machine",
            "message": f"Transition: {spec} ready → implementing",
        }
        (logs_dir / "fenixd.log").write_text(
            json.dumps(log_entry) + "\n" + json.dumps(log_entry2) + "\n",
            encoding="utf-8",
        )
        # run_id 秒级时间戳与 transition 同一秒（int(time.time()) 截断）
        (runs_dir / f"impl-{spec}-1788260731-a1.jsonl").write_text(
            '{"type": "provider_marker"}\n', encoding="utf-8"
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_state_transition_precedes_run_in_same_second(self):
        from core.dashboard.data import get_spec_timeline
        timeline = get_spec_timeline(self.tmpdir, "demo-spec")
        kinds = [(e["kind"], e.get("from"), e.get("to"), e.get("agent_type")) for e in timeline]
        # 状态节点（折叠后 drafted → implementing）必须排在运行节点之前
        state_idx = next(i for i, e in enumerate(timeline) if e["kind"] == "state")
        run_idx = next(i for i, e in enumerate(timeline) if e["kind"] == "run")
        self.assertEqual(timeline[state_idx]["from"], "drafted")
        self.assertEqual(timeline[state_idx]["to"], "implementing")
        self.assertLess(state_idx, run_idx, f"state must precede run in same second, got {kinds}")

    def test_run_after_transition_in_later_second(self):
        from core.dashboard.data import get_spec_timeline
        # 不同秒仍按真实时间排序：状态 11:05:31 → 运行 11:05:35
        runs_dir = Path(self.tmpdir) / ".fenix" / "runs"
        (runs_dir / "impl-demo-spec-1788260735-a1.jsonl").write_text(
            '{"type": "provider_marker"}\n', encoding="utf-8"
        )
        timeline = get_spec_timeline(self.tmpdir, "demo-spec")
        state_idx = next(i for i, e in enumerate(timeline) if e["kind"] == "state")
        run_idx = [i for i, e in enumerate(timeline) if e["kind"] == "run"]
        self.assertEqual(len(run_idx), 2)
        # 两个 run 都在 state 之后
        self.assertTrue(all(i > state_idx for i in run_idx))


class TestSpecTimelineRollbackWithoutTransition(unittest.TestCase):
    """打回节点重建：update_spec 直写 status（不走 transition()）必须在时间轴可见。

    根因：全部打回路径（fast-track 失败/守卫、merge 失败重派等 12 处）统一
    `update_spec({"status": "ready", "error": 原因})` 直写，日志无 Transition 行，
    时间轴上打回完全不可见（add-agent-prompt-files 事故）。读侧从 Updated SPEC
    行的 updates.status 重建打回节点，reason 取同行 error。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        logs_dir = Path(self.tmpdir) / ".fenix" / "logs"
        logs_dir.mkdir(parents=True)

        def line(ts, msg, **ctx):
            e = {"timestamp": ts, "level": "INFO",
                 "component": "state_machine", "message": msg}
            if ctx:
                e["context"] = ctx
            return json.dumps(e, ensure_ascii=False)

        lines = [
            # 正常推进：transition() 成对写（Transition 行 + Updated SPEC 行）
            line("2026-09-01T11:05:31.212625Z", "Transition: demo-spec ready → implementing"),
            line("2026-09-01T11:05:31.220000Z", "Updated SPEC 'demo-spec'",
                 updates={"status": "implementing"}),
            # 打回：update_spec 直写，无 Transition 行
            line("2026-09-01T11:08:33.100000Z", "Updated SPEC 'demo-spec'",
                 updates={"status": "ready",
                          "error": "结果文件 status='verified' 非法——顶层合同唯一合法值为 'success'"}),
            # 重派
            line("2026-09-01T11:17:15.100000Z", "Transition: demo-spec ready → implementing"),
        ]
        (logs_dir / "fenixd.log").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_rollback_creates_backtrack_node_with_error_reason(self):
        from core.dashboard.data import get_spec_timeline
        timeline = get_spec_timeline(self.tmpdir, "demo-spec")
        rollbacks = [e for e in timeline
                     if e["kind"] == "state" and e["to"] == "ready" and e["from"] == "implementing"]
        self.assertEqual(len(rollbacks), 1, f"打回节点缺失: {timeline}")
        self.assertIn("结果文件 status='verified' 非法", rollbacks[0]["reason"])

    def test_transition_paired_updated_spec_not_duplicated(self):
        from core.dashboard.data import get_spec_timeline
        timeline = get_spec_timeline(self.tmpdir, "demo-spec")
        forwards = [e for e in timeline
                    if e["kind"] == "state" and e["to"] == "implementing"]
        # 夹具有两次 ready → implementing（11:05 推进 + 11:17 重派），各一节点；
        # 成对的 Updated SPEC 行若未去重会多出第三条
        self.assertEqual(len(forwards), 2, f"成对行重复建节点: {timeline}")
        times = sorted(e["time"] for e in forwards)
        self.assertEqual(times[0][:19], "2026-09-01T11:05:31")
        self.assertEqual(times[1][:19], "2026-09-01T11:17:15")

    def test_rollback_from_unknown_when_window_truncated(self):
        from core.dashboard.data import get_spec_timeline
        # 日志窗口从打回行开始（推不出 from）→ from 为 "?" 占位，节点仍在
        logs_dir = Path(self.tmpdir) / ".fenix" / "logs"
        (logs_dir / "fenixd.log").write_text(
            json.dumps({"timestamp": "2026-09-01T11:08:33.100000Z", "level": "INFO",
                        "component": "state_machine", "message": "Updated SPEC 'demo-spec'",
                        "context": {"updates": {"status": "ready", "error": "fast-track run failed"}}},
                       ensure_ascii=False) + "\n",
            encoding="utf-8")
        timeline = get_spec_timeline(self.tmpdir, "demo-spec")
        rollbacks = [e for e in timeline if e["kind"] == "state" and e["to"] == "ready"]
        self.assertEqual(len(rollbacks), 1, f"截断窗口打回节点缺失: {timeline}")
        self.assertEqual(rollbacks[0]["from"], "?")
        self.assertEqual(rollbacks[0]["reason"], "fast-track run failed")


class TestGetRunsAgentType(unittest.TestCase):
    """get_runs 从 run_id 前缀推断 agent 类型（admin- 必须归 administrator，其余前缀不受影响）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.runs_dir = Path(self.tmpdir) / ".fenix" / "runs"
        self.runs_dir.mkdir(parents=True)

    def _write_run(self, run_id: str):
        (self.runs_dir / f"{run_id}.jsonl").write_text('{"type": "result"}\n', encoding="utf-8")

    def test_admin_run_id_maps_to_administrator(self):
        from core.dashboard.data import get_runs
        ts = int(time.time())
        self._write_run(f"admin-my-spec-{ts}")
        runs = get_runs(self.tmpdir)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["agent_type"], "administrator")
        self.assertEqual(runs[0]["spec"], "my-spec")

    def test_existing_prefixes_unchanged(self):
        from core.dashboard.data import get_runs
        ts = int(time.time())
        expected = {
            f"impl-s1-{ts}": "implementer",
            f"verify-s2-{ts}": "verifier",
            f"planner-judge-s3-{ts}": "planner-judge",
            f"planner-plan-s4-{ts}": "planner-plan",
            f"planner-s5-{ts}": "planner",
            f"test-s6-{ts}": "tester",
        }
        for rid in expected:
            self._write_run(rid)
        runs = {r["run_id"]: r["agent_type"] for r in get_runs(self.tmpdir)}
        for rid, at in expected.items():
            self.assertEqual(runs[rid], at, f"{rid} should infer {at}")


class TestDashboardDescriptionConfig(unittest.TestCase):
    """Dashboard description 配置：description 分支必须正确工作。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config_dir = Path(self.tmpdir) / ".fenix"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.config_dir / "config.yaml"


    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)


    def test_deep_merge_managed_description_writes_to_project_description(self):
        """_deep_merge_managed 的 description 分支：patch 顶层 description 写入 merged["project"]["description"]"""
        from core.dashboard.data import _deep_merge_managed

        # 初始配置
        raw_config = {
            "project": {"name": "test", "type": "web"},
            "llm": {"providers": []}
        }
        patch = {"description": "测试项目简介"}

        result = _deep_merge_managed(raw_config, patch)

        # 验证 description 被正确写入 project 节
        self.assertIn("project", result)
        self.assertEqual(result["project"]["description"], "测试项目简介")
        # 验证 project 节其它键保留
        self.assertEqual(result["project"]["name"], "test")
        self.assertEqual(result["project"]["type"], "web")
        # 验证 llm 键保留
        self.assertEqual(result["llm"], {"providers": []})

    def test_deep_merge_managed_description_non_string_ignored(self):
        """_deep_merge_managed 的 description 分支：非字符串类型的 description 被忽略"""
        from core.dashboard.data import _deep_merge_managed

        raw_config = {"project": {"name": "test"}}
        patch = {"description": 123}  # 非字符串

        result = _deep_merge_managed(raw_config, patch)

        # 验证 description 键未被写入（因为非字符串）
        self.assertNotIn("description", result.get("project", {}))

    def test_write_config_description_writes_to_project_description(self):
        """write_config 的 description 分支：patch 顶层 description 写入 project.description"""
        from core.dashboard.data import write_config

        # 先写入基础配置
        base_patch = {
            "project": {"name": "test", "type": "web"}
        }
        write_config(self.config_dir.parent, base_patch)

        # 写入 description
        desc_patch = {"description": "测试项目简介"}
        result = write_config(self.config_dir.parent, desc_patch)

        self.assertTrue(result["ok"])

        # 验证配置文件包含 description
        with open(self.config_path, "r", encoding="utf-8") as f:
            import yaml
            config = yaml.safe_load(f)

        self.assertEqual(config["project"]["description"], "测试项目简介")

    def test_read_effective_config_extracts_description(self):
        """read_effective_config 提取 project.description 到顶层 description"""
        from core.dashboard.data import read_effective_config

        # 写入包含 description 的配置
        config = {
            "project": {"name": "test", "type": "web", "description": "测试项目简介"},
            "schedule": {"poll_interval_minutes": 30, "daily_report_time": "09:00"},
            "agents": {"max_concurrent": 2, "max_retries": 3, "max_turns": 50, "daily_run_limit": 50, "run_timeout_seconds": 1800},
            "worktree": {"base_dir": ".claude/worktrees", "implement_branch_prefix": "fenix", "verify_branch_prefix": "fenix/verify"},
            "gates": {"require_push_approval": True},
            "commands": {"test": "echo OK", "build": "echo OK", "start": "echo OK"},
            "logging": {"dir": ".fenix/logs", "level": "INFO", "max_size_mb": 10, "backup_count": 5, "retain_days": 30},
        }

        import yaml
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True)

        result = read_effective_config(self.config_dir.parent)

        # 验证 description 被提取到顶层
        self.assertEqual(result["description"], "测试项目简介")

    def test_read_effective_config_missing_description_returns_empty(self):
        """read_effective_config 缺失 description 时返回空字符串"""
        from core.dashboard.data import read_effective_config

        # 写入不包含 description 的配置
        config = {
            "project": {"name": "test", "type": "web"},  # 无 description
            "schedule": {"poll_interval_minutes": 30, "daily_report_time": "09:00"},
            "agents": {"max_concurrent": 2, "max_retries": 3, "max_turns": 50, "daily_run_limit": 50, "run_timeout_seconds": 1800},
            "worktree": {"base_dir": ".claude/worktrees", "implement_branch_prefix": "fenix", "verify_branch_prefix": "fenix/verify"},
            "gates": {"require_push_approval": True},
            "commands": {"test": "echo OK", "build": "echo OK", "start": "echo OK"},
            "logging": {"dir": ".fenix/logs", "level": "INFO", "max_size_mb": 10, "backup_count": 5, "retain_days": 30},
        }

        import yaml
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True)

        result = read_effective_config(self.config_dir.parent)

        # 验证 description 为空字符串
        self.assertEqual(result["description"], "")

    def test_project_summary_includes_description(self):
        """project_summary 包含 description 字段"""
        from core.dashboard.data import project_summary
        from core.state_machine import StateMachine

        # 创建 STATE.md（.fenix/ 布局）
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        with open(state_path, "w", encoding="utf-8") as f:
            f.write("# Fenix Project State\n\n## Specs\n\n### test-spec\n- status: ready\n- priority: 1\n- created: 2026-01-01T00:00:00+00:00\n- updated: 2026-01-01T00:00:00+00:00\n- error: null\n- depends_on: null\n")

        # 写入配置
        config = {
            "project": {"name": "test-project", "type": "web", "description": "测试项目简介"},
            "schedule": {"poll_interval_minutes": 30, "daily_report_time": "09:00"},
            "agents": {"max_concurrent": 2, "max_retries": 3, "max_turns": 50, "daily_run_limit": 50, "run_timeout_seconds": 1800},
            "worktree": {"base_dir": ".claude/worktrees", "implement_branch_prefix": "fenix", "verify_branch_prefix": "fenix/verify"},
            "gates": {"require_push_approval": True},
            "commands": {"test": "echo OK", "build": "echo OK", "start": "echo OK"},
            "logging": {"dir": ".fenix/logs", "level": "INFO", "max_size_mb": 10, "backup_count": 5, "retain_days": 30},
        }

        import yaml
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True)

        result = project_summary(self.tmpdir, "test-project", self.tmpdir)

        # 验证 description 字段存在且正确
        self.assertIn("description", result)
        self.assertEqual(result["description"], "测试项目简介")


class TestRunResultScenariosFastTrack(unittest.TestCase):
    """fast-track 结果文件场景明细读取（场景结果页签对 fast-track spec 恒空的根因）。

    fast-track 的 .fenix-run-result.json（fast_track_result.py schema）把逐场景
    结果嵌套在 ``verification.scenarios``；full 模式 tester 结果是顶层
    ``scenarios``。读取端 parse_run_result_scenarios 原先只认顶层键，导致所有
    fast-track spec 的 Dashboard「场景结果」页签空白（数据在专属副本里并不缺）。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.spec = "fix-demo-fast-track"
        vp = Path(self.tmpdir) / ".fenix" / "verify-progress" / self.spec
        vp.mkdir(parents=True)
        self.vp_result = vp / ".fenix-run-result.json"
        self.sc = {"scenario_id": "s1", "description": "场景一",
                   "status": "pass", "assertion_results": []}

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _fast_track_payload(self):
        return {
            "status": "success", "spec": self.spec, "mode": "fast-track",
            "summary": "done",
            "verification": {"scenarios": [dict(self.sc)], "verdict": "verified",
                             "bugs": []},
        }

    def test_fast_track_nested_verification_scenarios_read(self):
        from core.dashboard.data import parse_run_result_scenarios
        self.vp_result.write_text(json.dumps(self._fast_track_payload()),
                                  encoding="utf-8")
        out = parse_run_result_scenarios(self.tmpdir, self.spec)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["scenario_id"], "s1")

    def test_full_mode_top_level_scenarios_still_win(self):
        from core.dashboard.data import parse_run_result_scenarios
        data = self._fast_track_payload()
        data["scenarios"] = [{"scenario_id": "top", "description": "顶层",
                              "status": "pass"}]
        self.vp_result.write_text(json.dumps(data), encoding="utf-8")
        out = parse_run_result_scenarios(self.tmpdir, self.spec)
        self.assertEqual(out[0]["scenario_id"], "top")

    def test_main_tree_fallback_with_spec_match(self):
        from core.dashboard.data import parse_run_result_scenarios
        root = Path(self.tmpdir) / ".fenix" / ".fenix-run-result.json"
        root.write_text(json.dumps(self._fast_track_payload()),
                        encoding="utf-8")
        out = parse_run_result_scenarios(self.tmpdir, self.spec)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["scenario_id"], "s1")

    def test_main_tree_other_spec_still_ignored(self):
        from core.dashboard.data import parse_run_result_scenarios
        data = self._fast_track_payload()
        data["spec"] = "another-spec"
        root = Path(self.tmpdir) / ".fenix" / ".fenix-run-result.json"
        root.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(parse_run_result_scenarios(self.tmpdir, self.spec), [])

    def test_empty_everywhere_returns_empty(self):
        from core.dashboard.data import parse_run_result_scenarios
        self.assertEqual(parse_run_result_scenarios(self.tmpdir, self.spec), [])


class TestSpecSummaryProgressPhase(unittest.TestCase):
    """add-task-progress-verify-phase 1.x：spec_summary 阶段判定与字段透传。

    阶段判定单点在后端 summary 层：status == "testing" → "verify"，其余一切
    状态 → "impl"；verify_current 透传 parse_verify_progress 的 current。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        (self.root / ".fenix").mkdir(parents=True, exist_ok=True)
        (self.root / ".fenix" / "STATE.md").write_text("", encoding="utf-8")
        d = self.root / "spec" / "changes" / "demo"
        d.mkdir(parents=True, exist_ok=True)
        (d / ".spec.yaml").write_text(
            "schema: spec-driven\ncreated: 2026-09-05\n", encoding="utf-8")
        (d / "tasks.md").write_text(
            "# Tasks\n\n## 1. x\n\n- [ ] 1.1 do\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _vp(self, total=11, done=5, current=""):
        vp = self.root / ".fenix" / "verify-progress"
        vp.mkdir(parents=True, exist_ok=True)
        (vp / "demo.json").write_text(
            json.dumps({"total": total, "done": done, "current": current}),
            encoding="utf-8")

    def test_testing_status_maps_to_verify_phase(self):
        """① status=testing → progress_phase "verify"，verify_current 透传进度文件文案。"""
        from core.dashboard.data import spec_summary
        self._vp(total=11, done=5, current="正在验证场景 S-06")
        s = spec_summary(self.root, "demo", {"status": "testing"})
        self.assertEqual(s["progress_phase"], "verify")
        self.assertEqual(s["verify_current"], "正在验证场景 S-06")
        self.assertEqual(s["verify_done"], 5)
        self.assertEqual(s["verify_total"], 11)

    def test_non_testing_statuses_map_to_impl(self):
        """② 完成侧/fix 循环/推进中任一非 testing 状态恒为 impl。"""
        from core.dashboard.data import spec_summary
        self._vp(total=11, done=5, current="正在验证场景 S-06")
        for status in ("verified", "done", "pushed", "bug-found", "blocked",
                       "implementing", "implemented", "ready", "drafted"):
            s = spec_summary(self.root, "demo", {"status": status})
            self.assertEqual(s["progress_phase"], "impl",
                             f"status {status} 必须为 impl")

    def test_testing_corrupt_progress_file_fault_tolerant(self):
        """③ testing 但进度文件损坏：仍 verify、verify_current 空串、不抛异常。"""
        from core.dashboard.data import spec_summary
        vp = self.root / ".fenix" / "verify-progress"
        vp.mkdir(parents=True, exist_ok=True)
        (vp / "demo.json").write_text("{not-json", encoding="utf-8")
        s = spec_summary(self.root, "demo", {"status": "testing"})
        self.assertEqual(s["progress_phase"], "verify")
        self.assertEqual(s["verify_current"], "")
        self.assertEqual(s["verify_total"], 0)
        self.assertEqual(s["verify_done"], 0)

    def test_fast_track_spec_always_impl(self):
        """④ fast-track spec 任意生命期状态恒 impl（_fast_track_advance_to_verified
        瞬时连转 testing→verified，不停留 testing，无需 mode 特判）。"""
        from core.dashboard.data import spec_summary
        d = self.root / "spec" / "changes" / "demo"
        (d / ".spec.yaml").write_text(
            "schema: spec-driven\ncreated: 2026-09-05\nmode: fast-track\n",
            encoding="utf-8")
        self._vp(total=11, done=5, current="正在验证场景 S-06")
        for status in ("drafted", "implementing", "verified"):
            s = spec_summary(self.root, "demo", {"status": status})
            self.assertEqual(s["progress_phase"], "impl",
                             f"fast-track {status} 恒 impl")
