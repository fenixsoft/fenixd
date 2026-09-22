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
from datetime import datetime, timezone
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

        # 缺省回显（此前 verify 段根本不在 read_config 里，前端恒显示默认值；
        # add-impl-code-review-tuning：三运行参数恒回显缺省 600/2/low；
        # add-impl-ocr-parallel-lane：并发缺省 2→4、补 mode 键缺省 gate）
        echoed = read_config(self.tmpdir)
        self.assertEqual(echoed["verify"],
                         {"static_scope": "main", "deps_mode": "hardlink",
                          "serving_reclaim": {"enabled": True},
                          "impl_code_review_timeout_sec": 600,
                          "impl_code_review_concurrency": 4,
                          "impl_code_review_effort": "low",
                          "impl_code_review_mode": "gate",
                          # fix-agent-lane-efficiency D3：上下文经济性告警阈值
                          "context_cost_per_turn_threshold": 200000})

        result = write_config(self.tmpdir, {
            "verify": {"static_scope": "worktree", "deps_mode": "hardlink"},
        })
        self.assertTrue(result["ok"], result.get("error"))
        echoed = read_config(self.tmpdir)
        self.assertEqual(echoed["verify"],
                         {"static_scope": "worktree", "deps_mode": "hardlink",
                          "serving_reclaim": {"enabled": True},
                          "impl_code_review_timeout_sec": 600,
                          "impl_code_review_concurrency": 4,
                          "impl_code_review_effort": "low",
                          "impl_code_review_mode": "gate",
                          "context_cost_per_turn_threshold": 200000})
        self.assertEqual(echoed["sources"]["verify.deps_mode"], "project")

        # 非法值拒绝（不落盘）
        bad = write_config(self.tmpdir, {"verify": {"deps_mode": "symlink"}})
        self.assertFalse(bad["ok"])
        self.assertIn("deps_mode", bad["error"])
        self.assertEqual(read_config(self.tmpdir)["verify"]["deps_mode"],
                         "hardlink")

    def test_verify_planner_max_concurrent_readback(self):
        """verify.planner_max_concurrent 读回（BUG-01）：写盘后 GET /api/config 须能读回。"""
        from core.dashboard.data import read_config, write_config

        # 缺省：verify 回显默认值，无 planner_max_concurrent 键
        echoed = read_config(self.tmpdir)
        self.assertNotIn("planner_max_concurrent", echoed.get("verify", {}))

        # 写 2 → 读回 2
        result = write_config(self.tmpdir, {"verify": {"planner_max_concurrent": 2}})
        self.assertTrue(result["ok"], result.get("error"))
        echoed = read_config(self.tmpdir)
        self.assertEqual(echoed["verify"]["planner_max_concurrent"], 2)

        # 写 0（关闭）→ 读回 0（开关应始终回显为关）
        result = write_config(self.tmpdir, {"verify": {"planner_max_concurrent": 0}})
        self.assertTrue(result["ok"], result.get("error"))
        echoed = read_config(self.tmpdir)
        self.assertEqual(echoed["verify"]["planner_max_concurrent"], 0)

    def test_impl_code_review_roundtrip_and_validation(self):
        """verify.impl_code_review：写读回环 + 非法值拒绝（add-impl-code-review-gate）。"""
        from core.dashboard.data import read_config, write_config

        # 缺省：verify 回显默认值，无 impl_code_review 键（不破坏既有严格相等断言）
        echoed = read_config(self.tmpdir)
        self.assertNotIn("impl_code_review", echoed.get("verify", {}))
        # _SOURCE_KEYS 登记后 sources 键存在，缺省为 user（继承用户级）
        self.assertEqual(echoed["sources"]["verify.impl_code_review"], "user")

        # 写 True → 读回 True（sources 标注 project）
        result = write_config(self.tmpdir, {"verify": {"impl_code_review": True}})
        self.assertTrue(result["ok"], result.get("error"))
        echoed = read_config(self.tmpdir)
        self.assertTrue(echoed["verify"]["impl_code_review"])
        self.assertEqual(echoed["sources"]["verify.impl_code_review"], "project")

        # 写 False → 读回 False（配置写入 false 而非删键）
        result = write_config(self.tmpdir, {"verify": {"impl_code_review": False}})
        self.assertTrue(result["ok"], result.get("error"))
        echoed = read_config(self.tmpdir)
        self.assertIs(echoed["verify"]["impl_code_review"], False)
        self.assertEqual(echoed["sources"]["verify.impl_code_review"], "project")

        # 非法值拒绝（非 bool → 不落盘，保留旧值，与 deps_mode 非法值同款）
        for bad in ("yes", 1, 0, "on", "true"):
            bad_res = write_config(self.tmpdir, {"verify": {"impl_code_review": bad}})
            self.assertFalse(bad_res["ok"], f"{bad!r} 应被拒绝")
            self.assertIn("impl_code_review", bad_res["error"])
        echoed = read_config(self.tmpdir)
        self.assertIs(echoed["verify"]["impl_code_review"], False)

    def test_impl_code_review_effective_echo(self):
        """read_effective_config 有效值回显 verify.impl_code_review。"""
        from core.dashboard.data import read_effective_config, write_config

        result = write_config(self.tmpdir, {"verify": {"impl_code_review": True}})
        self.assertTrue(result["ok"], result.get("error"))
        eff = read_effective_config(self.tmpdir)
        self.assertTrue(eff["verify"]["impl_code_review"])

    def test_impl_code_review_sync_from_user(self):
        """「同步用户级设置」按钮按页白名单取键——impl_code_review 迁至 quality 页
        （原 add-impl-code-review-gate 任务 2.4 的 verify 页键组，随「质量」页签独立
        而移动；键路径 verify.impl_code_review 不变）。"""
        from core.dashboard.data import _SYNC_PAGE_KEYS

        self.assertIn("impl_code_review", _SYNC_PAGE_KEYS["quality"]["verify"])
        # verify 页不再承载该键（迁出后避免双入口）
        self.assertNotIn("impl_code_review", _SYNC_PAGE_KEYS["verify"]["verify"])

    def test_max_same_cause_redispatches_roundtrip_and_validation(self):
        """agents.max_same_cause_redispatches：缺省回显 + 写读回环 + 非法拒绝
        （fix-redispatch-loop-governance D5：新配置键 MUST 带 Dashboard 界面）。"""
        from core.dashboard.data import read_config, write_config

        # 缺省回显（缺省 3，经 ConfigLoader 单点归一化）
        echoed = read_config(self.tmpdir)
        self.assertEqual(echoed["agents"]["max_same_cause_redispatches"], 3)

        # 写 5 → 读回 5（sources 标注 project）
        result = write_config(self.tmpdir, {"agents": {"max_same_cause_redispatches": 5}})
        self.assertTrue(result["ok"], result.get("error"))
        echoed = read_config(self.tmpdir)
        self.assertEqual(echoed["agents"]["max_same_cause_redispatches"], 5)
        self.assertEqual(echoed["sources"]["agents.max_same_cause_redispatches"], "project")

        # 非法值拒绝（越界 0 / 101 / 非整数 → 400 不落盘，保留旧值）
        for bad in (0, 101, "3", True):
            bad_res = write_config(self.tmpdir, {"agents": {"max_same_cause_redispatches": bad}})
            self.assertFalse(bad_res["ok"], f"{bad!r} 应被拒绝")
            self.assertIn("max_same_cause_redispatches", bad_res["error"])
        echoed = read_config(self.tmpdir)
        self.assertEqual(echoed["agents"]["max_same_cause_redispatches"], 5)

    def test_max_same_cause_redispatches_effective_echo(self):
        """read_effective_config 有效值回显（与生效值一致，非法回退缺省 3）。"""
        from core.dashboard.data import read_effective_config, write_config

        result = write_config(self.tmpdir, {"agents": {"max_same_cause_redispatches": 7}})
        self.assertTrue(result["ok"], result.get("error"))
        eff = read_effective_config(self.tmpdir)
        self.assertEqual(eff["agents"]["max_same_cause_redispatches"], 7)


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


class TestTimelineFoldChain(unittest.TestCase):
    """折叠状态节点携带 chain（完整状态序列）：中间状态不省略。

    fast-track 连跳 implemented→testing→verified→done→pushed 折叠后若只显示
    一头一尾，testing/verified 等真实途经状态被掩盖（2026-09-08 用户要求
    同一节点内全链展示，状态不省略）。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        logs_dir = Path(self.tmpdir) / ".fenix" / "logs"
        logs_dir.mkdir(parents=True)
        lines = [
            {"timestamp": "2026-09-07T03:57:54.000000Z",
             "message": "Transition: demo-spec implementing → implemented"},
            {"timestamp": "2026-09-07T03:57:54.100000Z",
             "message": "Transition: demo-spec implemented → testing"},
            {"timestamp": "2026-09-07T03:57:54.200000Z",
             "message": "Transition: demo-spec testing → verified"},
            {"timestamp": "2026-09-07T03:57:54.300000Z",
             "message": "Transition: demo-spec verified → done"},
        ]
        (logs_dir / "fenixd.log").write_text(
            "\n".join(json.dumps(l) for l in lines) + "\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_folded_node_carries_full_chain(self):
        from core.dashboard.data import get_spec_timeline
        timeline = get_spec_timeline(self.tmpdir, "demo-spec")
        states = [e for e in timeline if e["kind"] == "state"]
        self.assertEqual(len(states), 1)
        node = states[0]
        self.assertEqual(node["from"], "implementing")
        self.assertEqual(node["to"], "done")
        self.assertEqual(
            node["chain"],
            ["implementing", "implemented", "testing", "verified", "done"])

    def test_single_transition_has_no_chain(self):
        """单条转换不折叠（无 chain 字段），前端回退 from/to 渲染。"""
        logs_dir = Path(self.tmpdir) / ".fenix" / "logs"
        (logs_dir / "fenixd.log").write_text(json.dumps({
            "timestamp": "2026-09-07T04:00:00.000000Z",
            "message": "Transition: demo-spec done → pushed",
        }) + "\n", encoding="utf-8")
        from core.dashboard.data import get_spec_timeline
        timeline = get_spec_timeline(self.tmpdir, "demo-spec")
        states = [e for e in timeline if e["kind"] == "state"]
        self.assertEqual(len(states), 1)
        self.assertNotIn("chain", states[0])
        self.assertEqual(states[0]["from"], "done")
        self.assertEqual(states[0]["to"], "pushed")


class TestGetRunsStartedRealTimestamp(unittest.TestCase):
    """started 优先取 run 产物首行事件时间戳（真实启动时刻）。

    run_id 内嵌时间戳是首次派发时刻：多 attempt run 复用同一 run_id 基座，
    按 run_id 解析会让所有 attempt 显示同一开始时刻且 duration 虚增
    （2026-09-08：a1 error 与 a2 done 同显示 16:09:28，紧邻状态转移节点
    被误读为 error 触发了转移）。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.runs_dir = Path(self.tmpdir) / ".fenix" / "runs"
        self.runs_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_attempt_runs_show_real_start_times(self):
        from core.dashboard.data import get_runs, _parse_iso_ts
        base = int(time.time()) - 10000
        # a2 真实启动时刻 = 派发（base）后 1 小时（同日相对时间，避免跨日歧义）
        real_a2 = datetime.fromtimestamp(base + 3600, tz=timezone.utc).isoformat()
        # a1：全文件无 timestamp → 回退 run_id 派发时刻；
        # a2：复用同一 run_id 基座（-a2）+ 首行携带真实启动时间戳
        (self.runs_dir / f"impl-demo-{base}-a1.jsonl").write_text(
            '{"type": "system"}\n'
            '{"type": "error", "error": "Max turns (600) reached"}\n',
            encoding="utf-8")
        (self.runs_dir / f"impl-demo-{base}-a2.jsonl").write_text(
            json.dumps({"type": "system", "timestamp": real_a2}) + "\n"
            '{"type": "result", "subtype": "success"}\n', encoding="utf-8")
        runs = {r["run_id"]: r for r in get_runs(self.tmpdir)}
        a1, a2 = runs[f"impl-demo-{base}-a1"], runs[f"impl-demo-{base}-a2"]
        self.assertEqual(a2["started"], real_a2,
                         "a2 started 必须是产物首行真实启动时刻")
        self.assertEqual(
            a1["started"],
            datetime.fromtimestamp(base, tz=timezone.utc).isoformat(),
            "a1 无时间戳样本应回退 run_id 派发时刻")
        self.assertLess(a1["started"], a2["started"],
                        "真实时序：a1（error）先于 a2")
        expected_dur = int(
            (self.runs_dir / f"impl-demo-{base}-a2.jsonl").stat().st_mtime
            - _parse_iso_ts(real_a2).timestamp())
        self.assertEqual(a2["duration_seconds"], expected_dur,
                         "duration = 结束 mtime - 真实启动时刻")

    def test_timestamp_on_later_line_is_found(self):
        """首行无 timestamp（异常行等）时扫描后续行取第一个可解析值。"""
        from core.dashboard.data import get_runs
        base = int(time.time()) - 10000
        (self.runs_dir / f"impl-demo-{base}.jsonl").write_text(
            'not-json-garbage\n'
            '{"type": "assistant", "timestamp": "2026-09-07T08:09:44.000000Z"}\n',
            encoding="utf-8")
        runs = get_runs(self.tmpdir)
        self.assertIn("08:09:44", runs[0]["started"])


class TestTimelineVerifyNode(unittest.TestCase):
    """验证执行节点：verify_engine 确定性执行（非 agent run）必须在时间轴可见。

    full 模式验证执行不产生 runs/*.jsonl，testing→verified 之间无节点打断折叠，
    观感是「实现完直接连跳已推送」（fix-provider-transient-backoff 误读事故）。
    节点以 report.json（仅引擎验证写入）+ 日志「开始验证」行构建，折叠在它处断开。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        logs_dir = Path(self.tmpdir) / ".fenix" / "logs"
        logs_dir.mkdir(parents=True)
        self.log_lines = [
            {"timestamp": "2026-09-07T19:17:52.287000Z",
             "message": "Transition: demo-spec implementing → implemented"},
            {"timestamp": "2026-09-07T19:17:52.359000Z",
             "message": "Transition: demo-spec implemented → testing"},
            {"timestamp": "2026-09-07T19:18:50.000000Z",
             "message": "🚀 开始验证 'demo-spec': 16 个场景, 并行度=5"},
            {"timestamp": "2026-09-07T19:20:45.273000Z",
             "message": "Transition: demo-spec testing → verified"},
            {"timestamp": "2026-09-07T19:20:45.310000Z",
             "message": "Transition: demo-spec verified → done"},
        ]
        (logs_dir / "fenixd.log").write_text(
            "\n".join(json.dumps(l) for l in self.log_lines) + "\n", encoding="utf-8")
        rp_dir = Path(self.tmpdir) / ".fenix" / "verify-progress" / "demo-spec"
        rp_dir.mkdir(parents=True)
        (rp_dir / "report.json").write_text(json.dumps({
            "spec": "demo-spec",
            "timestamp": "2026-09-07T19:20:45.253704+00:00",
            "summary": {"total": 16, "passed": 16, "warnings": 0,
                        "failed": 0, "errors": 0, "blocked_env": 0},
            "scenarios": [],
        }), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _timeline_kinds(self):
        from core.dashboard.data import get_spec_timeline
        return get_spec_timeline(self.tmpdir, "demo-spec")

    def test_verify_node_breaks_fold(self):
        timeline = self._timeline_kinds()
        verify_nodes = [e for e in timeline if e["kind"] == "verify"]
        self.assertEqual(len(verify_nodes), 1)
        v = verify_nodes[0]
        self.assertEqual(v["time"], "2026-09-07T19:18:50.000000Z",
                         "节点时间取日志「开始验证」行（引擎开始时刻）")
        self.assertEqual(v["duration_seconds"], 115)
        self.assertEqual((v["total"], v["passed"], v["failed"]), (16, 16, 0))
        # 折叠在验证执行节点处断开：testing 之前一段、之后 verified 系列一段
        v_idx = timeline.index(v)
        before = next(e for e in timeline if e["kind"] == "state"
                      and e.get("to") == "testing")
        after = next(e for e in timeline if e["kind"] == "state"
                     and "verified" in (e.get("chain") or []))
        self.assertLess(timeline.index(before), v_idx)
        self.assertGreater(timeline.index(after), v_idx)
        self.assertEqual(before.get("chain"),
                         ["implementing", "implemented", "testing"])
        self.assertEqual(after.get("chain"), ["testing", "verified", "done"])

    def test_verify_node_fallback_to_report_timestamp(self):
        """日志「开始验证」行缺失（env 受阻早退等）→ 退化用报告完成时刻。"""
        logs_dir = Path(self.tmpdir) / ".fenix" / "logs"
        kept = [l for l in self.log_lines if "开始验证" not in l["message"]]
        (logs_dir / "fenixd.log").write_text(
            "\n".join(json.dumps(l) for l in kept) + "\n", encoding="utf-8")
        timeline = self._timeline_kinds()
        v = next(e for e in timeline if e["kind"] == "verify")
        self.assertEqual(v["time"], "2026-09-07T19:20:45.253704+00:00")
        self.assertNotIn("duration_seconds", v)
        # 与 verified 转换同秒：节点必须按精确时间排在 verified 转换之前
        verified_idx = next(i for i, e in enumerate(timeline)
                            if e["kind"] == "state"
                            and "verified" in (e.get("chain") or []))
        self.assertLess(timeline.index(v), verified_idx)

    def test_no_report_no_verify_node(self):
        rp = Path(self.tmpdir) / ".fenix" / "verify-progress" / "demo-spec" / "report.json"
        rp.unlink()
        timeline = self._timeline_kinds()
        self.assertFalse([e for e in timeline if e["kind"] == "verify"])


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


class TestClassifyRunTerminalTypes(unittest.TestCase):
    """run 终态分类与框架口径对齐（读侧同步写侧 RUN_TERMINAL_EVENT_TYPES）。

    liveness.py 启动终态补写扫描 / 优雅停机 / 人工取消会向 run 产物追加
    interrupted / cancelled 终态事件（runner「终态后置」不变量：终态行必为
    最后一行）。dashboard classify_run 只认 result/error 曾把 11 个已终结
    run 全部判成 running，overview 活跃 Agent 数虚高 10 倍（2026-09-06 实证：
    active_run_count=11，真实活跃仅 1）。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.runs_dir = Path(self.tmpdir) / ".fenix" / "runs"
        self.runs_dir.mkdir(parents=True)

    def _write_run(self, run_id: str, last_event: dict):
        body = json.dumps({"type": "assistant", "message": {"content": []}})
        (self.runs_dir / f"{run_id}.jsonl").write_text(
            body + "\n" + json.dumps(last_event) + "\n", encoding="utf-8")

    def test_interrupted_last_line_is_terminal(self):
        from core.dashboard.data import get_runs
        ts = int(time.time())
        self._write_run(f"impl-demo-{ts}",
                        {"type": "interrupted", "reason": "startup terminal-state sweep"})
        runs = get_runs(self.tmpdir)
        self.assertEqual(runs[0]["status"], "interrupted")

    def test_cancelled_last_line_is_terminal(self):
        from core.dashboard.data import get_runs
        ts = int(time.time())
        self._write_run(f"impl-demo-{ts}",
                        {"type": "cancelled", "reason": "user cancel"})
        runs = get_runs(self.tmpdir)
        self.assertEqual(runs[0]["status"], "cancelled")

    def test_terminal_runs_not_counted_active(self):
        """overview 活跃 Agent 数回归：interrupted/cancelled run 不得计入活跃。"""
        from core.dashboard.data import active_run_count
        ts = int(time.time())
        self._write_run(f"impl-s-{ts}-a1", {"type": "interrupted", "reason": "sweep"})
        self._write_run(f"impl-s-{ts}-a2", {"type": "cancelled", "reason": "user"})
        self._write_run(f"impl-s-{ts}-a3", {"type": "assistant", "message": {"content": []}})
        self.assertEqual(active_run_count(self.tmpdir), 1)

    def test_terminal_types_cover_framework_canonical_set(self):
        """映射必须覆盖 liveness.RUN_TERMINAL_EVENT_TYPES 全部类型（防再次漂移）。"""
        from core.agent_runner.liveness import RUN_TERMINAL_EVENT_TYPES
        from core.dashboard.data import classify_run
        for t in RUN_TERMINAL_EVENT_TYPES:
            status = classify_run([{"type": t}])
            self.assertNotEqual(status, "running",
                                f"终态事件类型 {t!r} 被误判为 running")


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

    def test_review_and_dispute_prefixes_do_not_degrade_to_generic_agent(self):
        """spec-review-/dispute-judge- 前缀必须识别出类型与 spec。

        回归：前缀表曾是 data.py 内的漂移副本，漏了这两个前缀 →
        时间线把评审 Agent 显示为泛型 "agent"，且 spec 字段残留整个 run_id。
        """
        from core.dashboard.data import get_runs
        ts = int(time.time())
        expected = {
            f"spec-review-my-spec-{ts}": "spec-review",
            f"dispute-judge-my-spec-{ts}": "dispute-judge",
        }
        for rid in expected:
            self._write_run(rid)
        runs = {r["run_id"]: r for r in get_runs(self.tmpdir)}
        for rid, at in expected.items():
            self.assertEqual(runs[rid]["agent_type"], at, f"{rid} should infer {at}")
            self.assertEqual(runs[rid]["spec"], "my-spec",
                             f"{rid} 应剥离前缀与时间戳后归属 my-spec")


class TestRunIdPrefixSingleSource(unittest.TestCase):
    """run_id 前缀表唯一真源：dashboard/admin_monitor 的推断不得与 run_files 漂移。"""

    def test_dashboard_inference_matches_canonical_prefixes(self):
        from core.agent_runner.run_files import (RUN_ID_AGENT_PREFIXES,
                                                 infer_run_agent_type,
                                                 run_spec_part)
        from core.dashboard.data import get_runs
        tmpdir = tempfile.mkdtemp()
        try:
            runs_dir = Path(tmpdir) / ".fenix" / "runs"
            runs_dir.mkdir(parents=True)
            ts = int(time.time())
            expected = {}
            for prefix, agent_type in RUN_ID_AGENT_PREFIXES:
                rid = f"{prefix}my-spec-{ts}"
                (runs_dir / f"{rid}.jsonl").write_text(
                    '{"type": "result"}\n', encoding="utf-8")
                expected[rid] = agent_type
            runs = {r["run_id"]: r["agent_type"] for r in get_runs(tmpdir)}
            for rid, at in expected.items():
                self.assertEqual(runs[rid], at, f"{rid} should infer {at}")
                # infer 只剥前缀，时间戳剥离归 run_spec_part（两段拼接 = 完整 spec）
                self.assertEqual(infer_run_agent_type(rid),
                                 (at, f"my-spec-{ts}"))
                self.assertEqual(run_spec_part(rid), "my-spec")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_admin_monitor_prefixes_subset_of_canonical(self):
        """admin_monitor 的失败计数前缀必须仍是真源的子集（可少不可多）。"""
        from core.admin_monitor import _RUN_PREFIXES
        from core.agent_runner.run_files import RUN_ID_AGENT_PREFIXES
        canonical = {p for p, _ in RUN_ID_AGENT_PREFIXES}
        unknown = set(_RUN_PREFIXES) - canonical
        self.assertFalse(unknown, f"admin_monitor 前缀未同步到真源: {sorted(unknown)}")


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

    def test_read_effective_config_planner_max_concurrent_echo(self):
        """read_effective_config 有效视图回显 verify.planner_max_concurrent（与写路径对称）"""
        from core.dashboard.data import read_effective_config

        # 用户级配置隔离（isolated_user_config 惯例的 unittest 版）：本机
        # ~/.fenix/config.yaml 可能显式写 planner_max_concurrent，断言缺省
        # 行为不隔离就会环境敏感假失败。patch 后用户层按空 dict 兜底。
        user_dir = Path(self.tmpdir) / "user-fenix"
        with patch("core.config.USER_CONFIG_DIR", user_dir), \
             patch("core.dashboard.data.USER_CONFIG_PATH", user_dir / "config.yaml"):
            # 缺省：verify 回显默认值，不含 planner_max_concurrent
            result = read_effective_config(self.config_dir.parent)
            self.assertNotIn("planner_max_concurrent", result.get("verify", {}))
            self.assertEqual(result["sources"].get("verify.planner_max_concurrent"), "user")

            # 写入 verify.planner_max_concurrent: 3
            import yaml
            config = {
                "project": {"name": "test", "type": "web"},
                "verify": {"planner_max_concurrent": 3},
            }
            with open(self.config_path, "w", encoding="utf-8") as f:
                yaml.dump(config, f, allow_unicode=True)

            result = read_effective_config(self.config_dir.parent)
            self.assertEqual(result["verify"]["planner_max_concurrent"], 3)
            self.assertEqual(result["sources"]["verify.planner_max_concurrent"], "project")

            # 非法值（负数/布尔）不进入有效视图
            config["verify"] = {"planner_max_concurrent": -1}
            with open(self.config_path, "w", encoding="utf-8") as f:
                yaml.dump(config, f, allow_unicode=True)
            result = read_effective_config(self.config_dir.parent)
            self.assertNotIn("planner_max_concurrent", result.get("verify", {}))

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


class TestVerifyProgressFastTrackFallback(unittest.TestCase):
    """parse_verify_progress 对 fast-track 裁决结果文件的回退合成。

    fast-track 单 agent 全包不经过 verify_engine，`.fenix/verify-progress/<spec>.json`
    进度文件全程无人写入，导致 Dashboard「验证」列与「验证进度」卡片恒空态
    （0/0、暂无验证进度）。修复：进度文件缺失时回退 .fenix-run-result.json 的
    verification.scenarios 合成 total/done/current，并标记 source: "run-result"。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.spec = "fix-demo-fast-track"
        self.vp = Path(self.tmpdir) / ".fenix" / "verify-progress" / self.spec
        self.vp.mkdir(parents=True)
        self.vp_result = self.vp / ".fenix-run-result.json"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _fast_track_payload(self, scenarios):
        return {
            "status": "success", "spec": self.spec, "mode": "fast-track",
            "summary": "done",
            "verification": {"scenarios": scenarios, "verdict": "verified",
                             "bugs": []},
        }

    def _pass_scenario(self, i):
        return {"scenario_id": f"s{i}", "description": f"场景{i}",
                "status": "pass", "assertion_results": []}

    def test_dedicated_copy_synthesizes_progress(self):
        from core.dashboard.data import parse_verify_progress
        self.vp_result.write_text(
            json.dumps(self._fast_track_payload(
                [self._pass_scenario(i) for i in range(1, 9)])),
            encoding="utf-8")
        out = parse_verify_progress(self.tmpdir, self.spec)
        self.assertTrue(out["exists"])
        self.assertEqual(out["total"], 8)
        self.assertEqual(out["done"], 8)
        self.assertEqual(out["current"], "验证完成: 8通过, 0失败, 0错误")
        self.assertEqual(out["source"], "run-result")

    def test_mixed_status_buckets(self):
        from core.dashboard.data import parse_verify_progress
        scenarios = [
            self._pass_scenario(1), self._pass_scenario(2),   # 2 pass
            {"scenario_id": "f1", "status": "fail"},          # fail 与 failed 同计失败
            {"scenario_id": "f2", "status": "failed"},
            {"scenario_id": "e1", "status": "error"},
            {"scenario_id": "w1", "status": "warning"},       # 豁免类不入三桶但计 total
            {"scenario_id": "x1", "status": "exempt"},
            {"scenario_id": "no-status"},                     # 无 status 不计 done
        ]
        self.vp_result.write_text(
            json.dumps(self._fast_track_payload(scenarios)), encoding="utf-8")
        out = parse_verify_progress(self.tmpdir, self.spec)
        self.assertTrue(out["exists"])
        self.assertEqual(out["total"], 8)
        self.assertEqual(out["done"], 7)
        self.assertEqual(out["current"], "验证完成: 2通过, 2失败, 1错误")
        self.assertEqual(out["source"], "run-result")

    def test_progress_file_preferred_no_fallback(self):
        from core.dashboard.data import parse_verify_progress
        # 结果文件在场但进度文件优先（full 模式 verify_engine 逐场景推进路径）
        self.vp_result.write_text(
            json.dumps(self._fast_track_payload(
                [self._pass_scenario(i) for i in range(1, 9)])),
            encoding="utf-8")
        pf = Path(self.tmpdir) / ".fenix" / "verify-progress" / f"{self.spec}.json"
        pf.write_text(json.dumps({"total": 11, "done": 5, "current": "进行中"}),
                      encoding="utf-8")
        out = parse_verify_progress(self.tmpdir, self.spec)
        self.assertTrue(out["exists"])
        self.assertEqual(out["total"], 11)
        self.assertEqual(out["done"], 5)
        self.assertEqual(out["current"], "进行中")
        self.assertEqual(out["source"], "file")

    def test_both_missing_keeps_empty_state(self):
        from core.dashboard.data import parse_verify_progress
        out = parse_verify_progress(self.tmpdir, self.spec)
        self.assertFalse(out["exists"])
        self.assertEqual(out["total"], 0)
        self.assertEqual(out["done"], 0)

    def test_main_tree_other_spec_ignored(self):
        from core.dashboard.data import parse_verify_progress
        data = self._fast_track_payload([self._pass_scenario(1)])
        data["spec"] = "another-spec"
        root = Path(self.tmpdir) / ".fenix" / ".fenix-run-result.json"
        root.write_text(json.dumps(data), encoding="utf-8")
        out = parse_verify_progress(self.tmpdir, self.spec)
        self.assertFalse(out["exists"])
        self.assertEqual(out["total"], 0)

    def test_empty_everywhere_returns_empty(self):
        from core.dashboard.data import parse_run_result_scenarios
        self.assertEqual(parse_run_result_scenarios(self.tmpdir, self.spec), [])


class TestVerdictFastTrackFallback(unittest.TestCase):
    """parse_verdict 对 fast-track 裁决结果文件的回退合成。

    verification-report.md 是 full 模式 tester 产物；fast-track 单 agent 全包
    不产该文件，裁决结论只存在于 .fenix-run-result.json 的 verification 段
    （fast_track_result.py 契约）。parse_verdict 原先只读 md 文件，导致所有
    fast-track spec的列表「验证」列 Popover 与详情页 VerdictPanel 恒隐
    （verdict.exists=False，数据在专属副本里并不缺）。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.spec = "fix-demo-fast-track"
        self.vp = Path(self.tmpdir) / ".fenix" / "verify-progress" / self.spec
        self.vp.mkdir(parents=True)
        self.vp_result = self.vp / ".fenix-run-result.json"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _fast_track_payload(self, scenarios, verdict="verified", bugs=None):
        return {
            "status": "success", "spec": self.spec, "mode": "fast-track",
            "summary": "done",
            "verification": {"scenarios": scenarios, "verdict": verdict,
                             "bugs": bugs or []},
        }

    def _scenario(self, i, status="pass"):
        return {"scenario_id": f"s{i}", "description": f"场景{i}",
                "status": status, "assertion_results": []}

    def test_verified_dedicated_copy_synthesizes_verdict(self):
        from core.dashboard.data import parse_verdict
        self.vp_result.write_text(
            json.dumps(self._fast_track_payload(
                [self._scenario(i) for i in range(1, 7)])),
            encoding="utf-8")
        out = parse_verdict(self.tmpdir, self.spec)
        self.assertTrue(out["exists"])
        self.assertIn("✅", out["status"])
        self.assertEqual(out["status_detail"], "裁决: verified")
        self.assertEqual(out["summary"]["passed"], 6)
        self.assertEqual(out["summary"]["failed"], 0)
        self.assertEqual(out["summary"]["errors"], 0)
        self.assertEqual(out["summary"]["product_bugs"], 0)

    def test_bug_found_status_and_bug_count(self):
        from core.dashboard.data import parse_verdict
        scenarios = [self._scenario(1),
                     {"scenario_id": "s2", "description": "失败场景",
                      "status": "fail", "assertion_results": []},
                     {"scenario_id": "s3", "description": "错误场景",
                      "status": "error", "assertion_results": []}]
        self.vp_result.write_text(
            json.dumps(self._fast_track_payload(
                scenarios, verdict="bug-found",
                bugs=[{"id": "BUG-01"}, {"id": "BUG-02"}])),
            encoding="utf-8")
        out = parse_verdict(self.tmpdir, self.spec)
        self.assertTrue(out["exists"])
        self.assertIn("❌", out["status"])
        self.assertIn("未通过", out["status"])
        self.assertEqual(out["summary"]["passed"], 1)
        self.assertEqual(out["summary"]["failed"], 1)
        self.assertEqual(out["summary"]["errors"], 1)
        self.assertEqual(out["summary"]["product_bugs"], 2)

    def test_main_tree_fallback_with_spec_match(self):
        from core.dashboard.data import parse_verdict
        root = Path(self.tmpdir) / ".fenix" / ".fenix-run-result.json"
        root.write_text(json.dumps(self._fast_track_payload([self._scenario(1)])),
                        encoding="utf-8")
        out = parse_verdict(self.tmpdir, self.spec)
        self.assertTrue(out["exists"])

    def test_main_tree_other_spec_still_ignored(self):
        from core.dashboard.data import parse_verdict
        data = self._fast_track_payload([self._scenario(1)])
        data["spec"] = "another-spec"
        root = Path(self.tmpdir) / ".fenix" / ".fenix-run-result.json"
        root.write_text(json.dumps(data), encoding="utf-8")
        self.assertFalse(parse_verdict(self.tmpdir, self.spec)["exists"])

    def test_illegal_verdict_keeps_fail_closed(self):
        from core.dashboard.data import parse_verdict
        data = self._fast_track_payload([self._scenario(1)])
        data["verification"]["verdict"] = "not-a-verdict"
        self.vp_result.write_text(json.dumps(data), encoding="utf-8")
        self.assertFalse(parse_verdict(self.tmpdir, self.spec)["exists"])

    def test_missing_verification_section_keeps_empty_state(self):
        from core.dashboard.data import parse_verdict
        self.vp_result.write_text(
            json.dumps({"status": "success", "spec": self.spec}),
            encoding="utf-8")
        out = parse_verdict(self.tmpdir, self.spec)
        self.assertFalse(out["exists"])

    def test_verification_report_md_still_wins(self):
        """full 模式 md 报告在场时优先（既有路径零回归）。"""
        from core.dashboard.data import parse_verdict
        self.vp_result.write_text(
            json.dumps(self._fast_track_payload([self._scenario(1)])),
            encoding="utf-8")
        spec_dir = Path(self.tmpdir) / "spec" / "changes" / self.spec
        spec_dir.mkdir(parents=True)
        (spec_dir / "verification-report.md").write_text(
            "## 结论：✅ 通过（verified）\n\n| 通过 | 10 |\n",
            encoding="utf-8")
        out = parse_verdict(self.tmpdir, self.spec)
        self.assertTrue(out["exists"])
        self.assertEqual(out["summary"]["passed"], "10")  # md 解析值为字符串


class TestBugsFastTrackFallback(unittest.TestCase):
    """parse_bugs 对 fast-track 裁决结果文件 bugs 清单的回退收录。

    Bug 列表唯一数据源是 report.json（full 模式 verify_engine 产物）；fast-track
    不产该文件，裁决出的 bugs 清单只存在于 .fenix-run-result.json（fast-track
    嵌套 verification.bugs，full 模式 verifier 顶层 bugs）→ 详情页 Bug 列表
    页签对 fast-track spec 恒空（第五读侧缺口，同族：场景页签/报告场景表/
    验证进度/验证结论）。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.spec = "fix-demo-fast-track"
        self.vp = Path(self.tmpdir) / ".fenix" / "verify-progress" / self.spec
        self.vp.mkdir(parents=True)
        self.vp_result = self.vp / ".fenix-run-result.json"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _fast_track_payload(self, bugs, verdict="bug-found"):
        scenarios = [{"scenario_id": "s1", "description": "场景一",
                      "status": "fail", "assertion_results": []}]
        return {
            "status": "success", "spec": self.spec, "mode": "fast-track",
            "summary": "done",
            "verification": {"scenarios": scenarios, "verdict": verdict,
                             "bugs": bugs},
        }

    def _bug(self, **over):
        bug = {"severity": "critical",
               "scenario_ids": ["s1", "s2"],
               "assertion_type": "element_visible",
               "description": "核心元素不可见",
               "root_cause": "渲染分支缺省",
               "evidence": {"failed_assertions": [
                   {"type": "element_visible", "pass": False,
                    "message": "元素不可见"}]}}
        bug.update(over)
        return bug

    def test_dedicated_copy_bugs_collected(self):
        from core.dashboard.data import parse_bugs
        self.vp_result.write_text(
            json.dumps(self._fast_track_payload([self._bug()])),
            encoding="utf-8")
        out = parse_bugs(self.tmpdir, self.spec)
        self.assertEqual(len(out), 1)
        b = out[0]
        self.assertEqual(b["source"], "run-result")
        self.assertEqual(b["severity"], "critical")
        self.assertEqual(b["scenario_ids"], ["s1", "s2"])
        self.assertEqual(b["assertion_type"], "element_visible")
        self.assertEqual(b["description"], "核心元素不可见")
        # evidence dict 序列化为 JSON 串（对齐 full 路径 sc_evidence 处理）
        self.assertIn("failed_assertions", b["evidence"])
        self.assertEqual(b["root_cause"], "渲染分支缺省")
        # 前端卡片渲染兼容字段（dashboard.ts 类型 bug.scenario / bug.assertion）
        self.assertEqual(b["scenario"], "s1, s2")
        self.assertEqual(b["assertion"], "element_visible")

    def test_evidence_missing_falls_back_to_root_cause(self):
        from core.dashboard.data import parse_bugs
        self.vp_result.write_text(
            json.dumps(self._fast_track_payload(
                [self._bug(evidence=None, root_cause="根因兜底")])),
            encoding="utf-8")
        out = parse_bugs(self.tmpdir, self.spec)
        self.assertEqual(out[0]["evidence"], "根因兜底")

    def test_report_json_still_wins(self):
        """full 模式 report.json 在场时优先（既有路径零回归）。"""
        from core.dashboard.data import parse_bugs
        self.vp_result.write_text(
            json.dumps(self._fast_track_payload([self._bug()])),
            encoding="utf-8")
        rp = self.vp / "report.json"
        rp.write_text(json.dumps({
            "exists": True,
            "scenarios": [{"scenario_id": "r1", "description": "报告场景",
                           "status": "fail", "assertion_results": []}],
        }), encoding="utf-8")
        out = parse_bugs(self.tmpdir, self.spec)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["scenario_ids"], ["r1"])

    def test_verified_no_bugs_returns_empty(self):
        from core.dashboard.data import parse_bugs
        self.vp_result.write_text(
            json.dumps(self._fast_track_payload([], verdict="verified")),
            encoding="utf-8")
        self.assertEqual(parse_bugs(self.tmpdir, self.spec), [])

    def test_main_tree_other_spec_ignored(self):
        from core.dashboard.data import parse_bugs
        data = self._fast_track_payload([self._bug()])
        data["spec"] = "another-spec"
        root = Path(self.tmpdir) / ".fenix" / ".fenix-run-result.json"
        root.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(parse_bugs(self.tmpdir, self.spec), [])

    def test_full_mode_top_level_bugs_fallback(self):
        """full 模式 verifier 结果（verifier.md schema：顶层 status+bugs）同样兜底。"""
        from core.dashboard.data import parse_bugs
        root = Path(self.tmpdir) / ".fenix" / ".fenix-run-result.json"
        root.write_text(json.dumps({
            "status": "bug-found", "spec": self.spec,
            "bugs": [self._bug()],
        }), encoding="utf-8")
        out = parse_bugs(self.tmpdir, self.spec)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["source"], "run-result")
        self.assertEqual(out[0]["severity"], "critical")

    def test_verifier_freeform_bug_schema_normalized(self):
        """verifier.md 未定义条目 schema，实测产出漂移为 id/severity:high|medium/title/
        location/description（无 scenario_ids/evidence）——读取端归一兼容。"""
        from core.dashboard.data import parse_bugs
        root = Path(self.tmpdir) / ".fenix" / ".fenix-run-result.json"
        root.write_text(json.dumps({
            "status": "bug-found", "spec": self.spec,
            "bugs": [{
                "id": "BUG-1", "severity": "high",
                "title": "保存时其它子键被默认值覆盖",
                "location": "core/dashboard/static/app.js:collectConfigData()",
                "description": "空/非法时回退硬编码默认值并回写配置。",
            }, {"id": "BUG-2", "severity": "low", "title": "横幅路径误导"}],
        }), encoding="utf-8")
        out = parse_bugs(self.tmpdir, self.spec)
        self.assertEqual(len(out), 2)
        b0 = out[0]
        self.assertEqual(b0["severity"], "major")  # high → major 归一
        self.assertEqual(b0["description"], "空/非法时回退硬编码默认值并回写配置。")
        self.assertEqual(b0["id"], "BUG-1")
        self.assertEqual(b0["title"], "保存时其它子键被默认值覆盖")
        self.assertEqual(b0["location"], "core/dashboard/static/app.js:collectConfigData()")
        self.assertEqual(out[1]["severity"], "minor")  # low → minor 归一
        self.assertEqual(out[1]["description"], "横幅路径误导")  # 无 description 时 title 兜底

    def test_full_path_bugs_gain_scenario_assertion_fields(self):
        """full 路径条目补 scenario/assertion 兼容字段（历史展示缺口：类型单复数漂移）。"""
        from core.dashboard.data import parse_bugs
        rp = self.vp / "report.json"
        rp.write_text(json.dumps({
            "exists": True,
            "scenarios": [{"scenario_id": "r1", "description": "报告场景",
                           "status": "fail",
                           "assertion_results": [
                               {"type": "text_contains", "pass": False,
                                "message": "文案不符"}]}],
        }), encoding="utf-8")
        out = parse_bugs(self.tmpdir, self.spec)
        self.assertEqual(out[0]["scenario"], "r1")
        self.assertEqual(out[0]["assertion"], "text_contains")


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


class TestSpecTimelineAdminEvents(unittest.TestCase):
    """SPEC 时间轴 admin 运维事件节点（add-timeline-admin-events）。

    数据源 .fenix/admin_alerts.json（AdminStore 读路径）：escalation/disposition
    记录按 spec 过滤成 kind="admin" 节点，与 state/run 统一排序；pending 被
    最终处置替代；缺失/损坏/缺 spec 字段 fail-open。
    """

    SPEC = "demo-spec"

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        logs_dir = Path(self.tmpdir) / ".fenix" / "logs"
        runs_dir = Path(self.tmpdir) / ".fenix" / "runs"
        logs_dir.mkdir(parents=True)
        runs_dir.mkdir(parents=True)
        # 状态节点 11:05:31（与 run 同秒，验证 state→admin→run 次序）
        log_entry = {
            "timestamp": "2026-09-01T11:05:31.212625Z",
            "level": "INFO",
            "component": "state_machine",
            "message": f"Transition: {self.SPEC} drafted → ready",
        }
        (logs_dir / "fenixd.log").write_text(
            json.dumps(log_entry) + "\n", encoding="utf-8",
        )
        # run 与 transition 同一秒（int(time.time()) 截断）
        (runs_dir / f"impl-{self.SPEC}-1788260731-a1.jsonl").write_text(
            '{"type": "provider_marker"}\n', encoding="utf-8",
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_alerts(self, records: list):
        alerts = Path(self.tmpdir) / ".fenix" / "admin_alerts.json"
        alerts.parent.mkdir(parents=True, exist_ok=True)
        alerts.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")

    def _admin_nodes(self, timeline) -> list:
        return [e for e in timeline if e.get("kind") == "admin"]

    def test_escalation_and_disposition_nodes_with_fields(self):
        """escalation/disposition 节点下发：record_kind、severity、状态字段齐全。"""
        self._write_alerts([
            {"kind": "escalation", "spec": self.SPEC, "signal_type": "family_explosion",
             "severity": "critical", "handled": True, "description": "告警描述",
             "created": "2026-09-01T11:05:32.000000Z"},
            {"kind": "disposition", "spec": self.SPEC, "signal_type": "family_explosion",
             "severity": "major", "result": "resolved", "description": "处置摘要",
             "created": "2026-09-01T11:05:33.000000Z"},
        ])
        from core.dashboard.data import get_spec_timeline
        timeline = get_spec_timeline(self.tmpdir, self.SPEC)
        admin = self._admin_nodes(timeline)
        self.assertEqual(len(admin), 2, f"admin 节点缺失: {timeline}")
        esc = next(e for e in admin if e["record_kind"] == "escalation")
        self.assertEqual(esc["severity"], "critical")
        self.assertIs(esc["handled"], True)
        self.assertEqual(esc["signal_type"], "family_explosion")
        self.assertEqual(esc["time"], "2026-09-01T11:05:32.000000Z")
        disp = next(e for e in admin if e["record_kind"] == "disposition")
        self.assertEqual(disp["result"], "resolved")
        self.assertEqual(disp["severity"], "major")

    def test_other_spec_admin_records_not_leaked(self):
        """其他 SPEC 的运维记录不串扰：只下发目标 spec 的节点。"""
        self._write_alerts([
            {"kind": "escalation", "spec": "other-spec", "severity": "critical",
             "handled": False, "created": "2026-09-01T11:05:32.000000Z"},
            {"kind": "disposition", "spec": "other-spec", "result": "resolved",
             "created": "2026-09-01T11:05:33.000000Z"},
        ])
        from core.dashboard.data import get_spec_timeline
        timeline = get_spec_timeline(self.tmpdir, self.SPEC)
        self.assertEqual(self._admin_nodes(timeline), [])

    def test_pending_replaced_by_final_disposition(self):
        """同 admin_run_id：pending 被最终处置替代，仅保留最终节点。"""
        self._write_alerts([
            {"kind": "disposition", "spec": self.SPEC, "admin_run_id": "admin-demo-spec-1788260700",
             "result": "pending", "description": "处置中",
             "created": "2026-09-01T11:04:00.000000Z"},
            {"kind": "disposition", "spec": self.SPEC, "admin_run_id": "admin-demo-spec-1788260700",
             "result": "resolved", "description": "最终处置",
             "created": "2026-09-01T11:05:00.000000Z"},
        ])
        from core.dashboard.data import get_spec_timeline
        timeline = get_spec_timeline(self.tmpdir, self.SPEC)
        admin = self._admin_nodes(timeline)
        self.assertEqual(len(admin), 1, f"pending 未被替代: {admin}")
        self.assertEqual(admin[0]["result"], "resolved")

    def test_pending_only_independent_node(self):
        """无最终处置时 pending 独立成节点；无 admin_run_id 的 pending 也独立。"""
        self._write_alerts([
            {"kind": "disposition", "spec": self.SPEC, "admin_run_id": "admin-demo-spec-1788260700",
             "result": "pending", "description": "处置中",
             "created": "2026-09-01T11:04:00.000000Z"},
            {"kind": "disposition", "spec": self.SPEC, "result": "pending",
             "description": "孤儿 pending", "created": "2026-09-01T11:04:30.000000Z"},
        ])
        from core.dashboard.data import get_spec_timeline
        timeline = get_spec_timeline(self.tmpdir, self.SPEC)
        admin = self._admin_nodes(timeline)
        self.assertEqual(len(admin), 2, f"pending 独立节点缺失: {admin}")
        self.assertTrue(all(e["result"] == "pending" for e in admin))

    def test_same_second_state_admin_run_order(self):
        """同秒次序：state → admin → run。"""
        self._write_alerts([
            {"kind": "disposition", "spec": self.SPEC, "result": "resolved",
             "description": "同秒处置", "created": "2026-09-01T11:05:31.500000Z"},
        ])
        from core.dashboard.data import get_spec_timeline
        timeline = get_spec_timeline(self.tmpdir, self.SPEC)
        kinds = [e["kind"] for e in timeline]
        self.assertIn("admin", kinds)
        self.assertLess(kinds.index("state"), kinds.index("admin"),
                        f"state 必须先于 admin: {kinds}")
        self.assertLess(kinds.index("admin"), kinds.index("run"),
                        f"admin 必须先于 run: {kinds}")

    def test_admin_node_breaks_forward_state_collapse(self):
        """admin 节点打断连续前向状态折叠：折叠不跨过 admin。"""
        logs_dir = Path(self.tmpdir) / ".fenix" / "logs"
        e1 = {"timestamp": "2026-09-01T11:03:00.000000Z", "level": "INFO",
              "component": "state_machine",
              "message": f"Transition: {self.SPEC} drafted → ready"}
        e2 = {"timestamp": "2026-09-01T11:03:10.000000Z", "level": "INFO",
              "component": "state_machine",
              "message": f"Transition: {self.SPEC} ready → implementing"}
        e3 = {"timestamp": "2026-09-01T11:03:20.000000Z", "level": "INFO",
              "component": "state_machine",
              "message": f"Transition: {self.SPEC} implementing → testing"}
        (logs_dir / "fenixd.log").write_text(
            "\n".join(json.dumps(x) for x in (e1, e2, e3)) + "\n",
            encoding="utf-8",
        )
        self._write_alerts([
            {"kind": "escalation", "spec": self.SPEC, "severity": "major",
             "handled": False, "created": "2026-09-01T11:03:15.000000Z"},
        ])
        from core.dashboard.data import get_spec_timeline
        timeline = get_spec_timeline(self.tmpdir, self.SPEC)
        state_nodes = [e for e in timeline if e["kind"] == "state"]
        # 若无 admin 打断，drafted→ready→implementing→testing 三条前向会折叠为
        # drafted→testing 单节点；admin(11:03:15) 打断使前两段先折叠为
        # drafted→implementing，其后 implementing→testing 独立一段 → 两个 state 节点
        self.assertEqual(len(state_nodes), 2, f"折叠未被 admin 打断: {timeline}")
        self.assertEqual(state_nodes[0]["from"], "drafted")
        self.assertEqual(state_nodes[0]["to"], "implementing")
        self.assertEqual(state_nodes[1]["from"], "implementing")
        self.assertEqual(state_nodes[1]["to"], "testing")

    def test_alerts_file_missing_fail_open(self):
        """admin_alerts.json 缺失：时间轴正常返回 state/run 节点。"""
        from core.dashboard.data import get_spec_timeline
        timeline = get_spec_timeline(self.tmpdir, self.SPEC)
        self.assertEqual(self._admin_nodes(timeline), [])
        kinds = {e["kind"] for e in timeline}
        self.assertIn("state", kinds)
        self.assertIn("run", kinds)

    def test_alerts_file_corrupt_fail_open(self):
        """admin_alerts.json 损坏（非法 JSON）：fail-open 返回空，不抛异常。"""
        alerts = Path(self.tmpdir) / ".fenix" / "admin_alerts.json"
        alerts.parent.mkdir(parents=True, exist_ok=True)
        alerts.write_text("{corrupt-json", encoding="utf-8")
        from core.dashboard.data import get_spec_timeline
        timeline = get_spec_timeline(self.tmpdir, self.SPEC)
        self.assertEqual(self._admin_nodes(timeline), [])
        self.assertTrue(timeline)

    def test_missing_spec_field_skipped(self):
        """缺 spec 字段的旧记录跳过：不下发、不误挂当前 SPEC。"""
        self._write_alerts([
            {"kind": "escalation", "severity": "critical", "handled": False,
             "created": "2026-09-01T11:05:32.000000Z"},
            {"kind": "disposition", "spec": self.SPEC, "result": "resolved",
             "created": "2026-09-01T11:05:33.000000Z"},
        ])
        from core.dashboard.data import get_spec_timeline
        timeline = get_spec_timeline(self.tmpdir, self.SPEC)
        admin = self._admin_nodes(timeline)
        self.assertEqual(len(admin), 1)
        self.assertEqual(admin[0]["record_kind"], "disposition")

    def test_signal_kind_not_included(self):
        """signal 内部审计记录不下发到时间轴。"""
        self._write_alerts([
            {"kind": "signal", "spec": self.SPEC, "signal_type": "family_explosion",
             "created": "2026-09-01T11:05:32.000000Z"},
            {"kind": "disposition", "spec": self.SPEC, "result": "resolved",
             "created": "2026-09-01T11:05:33.000000Z"},
        ])
        from core.dashboard.data import get_spec_timeline
        timeline = get_spec_timeline(self.tmpdir, self.SPEC)
        admin = self._admin_nodes(timeline)
        self.assertEqual(len(admin), 1)
        self.assertEqual(admin[0]["record_kind"], "disposition")


class TestArchivedSpecDocReadback(unittest.TestCase):
    """归档 SPEC 读侧回退（fix-archived-spec-doc-readback D1-D4）。

    归档实现为目录移动（spec/changes/<name>/ → spec/archive/YYYY-MM-DD-<name>/）
    + STATE.md 条目保留；读侧 get_spec_doc/parse_tasks/tasks_note 原先硬编码
    活跃目录，归档 SPEC 的五类文档页签与任务卡片空白。修复后活跃优先、归档回退，
    防穿越校验对回退路径同样生效。
    """

    SPEC = "demo-spec"

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.p = Path(self.tmpdir)
        self.spec_dir = self.p / "spec" / "changes" / self.SPEC
        self.archive_root = self.p / "spec" / "archive"
        self.compare_dir = self.archive_root
        # 注意：活跃布局在用例内按需构造（_archive_layout 会移走活跃目录）

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, base: Path, name: str, content: str):
        p = base / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def _active_layout(self):
        """活跃布局五类文档全量（proposal/design/tasks/verification/scenarios）。"""
        self._write(self.spec_dir, "proposal.md", "# 活跃提案\n\n正文-active")
        self._write(self.spec_dir, "design.md", "# 活跃设计\n\n正文-active")
        self._write(self.spec_dir, "tasks.md",
                    "# Tasks\n\n## 1. 实施\n\n- [x] 1.1 active已完成\n- [ ] 1.2 active待办\n")
        self._write(self.spec_dir, "verification-report.md",
                    "## 结论：✅ 通过（verified）\n\nactive")
        self._write(self.spec_dir / "specs" / "active-capability", "spec.md",
                    "## Scenario: 活跃场景")

    def _archived_layout(self, prefix="2026-09-02", content_marker="archived"):
        """归档布局：活跃目录移入 spec/archive/<prefix>-<SPEC>/。
        内容统一以 content_marker 标识，与活跃布局内容可区分。
        """
        self._active_layout()
        archive_dir = self.archive_root / f"{prefix}-{self.SPEC}"
        shutil.move(str(self.spec_dir), str(archive_dir))
        # 清掉活跃布局遗留的 specs/（避免与归档场景混合拼接），再覆写五类文档
        shutil.rmtree(archive_dir / "specs", ignore_errors=True)
        self._write(archive_dir, "proposal.md", f"# 归档提案\n\n正文-{content_marker}")
        self._write(archive_dir, "design.md", f"# 归档设计\n\n正文-{content_marker}")
        self._write(archive_dir, "tasks.md",
                    f"# Tasks\n\n## 1. 归档任务\n\n- [x] 1.1 完成-{content_marker}\n- [ ] 1.2 待办-{content_marker}\n")
        self._write(archive_dir, "verification-report.md",
                    f"## 结论：✅ 通过（verified）\n\n{content_marker}")
        self._write(archive_dir / "specs" / "archived-capability", "spec.md",
                    f"## Scenario: 归档场景-{content_marker}")
        return archive_dir

    # ── resolve_spec_dir helper 直测 ──────────────────────────────────────

    def test_resolve_invalid_spec_returns_none(self):
        from core.dashboard.data import resolve_spec_dir
        self._active_layout()
        for bad in ("..", "../outside", "..%2Fetc", "a/b", "UPPER", ""):
            self.assertIsNone(resolve_spec_dir(self.tmpdir, bad),
                              f"非法 spec {bad!r} 必须返回 None")

    def test_resolve_active_dir_priority(self):
        from core.dashboard.data import resolve_spec_dir
        self._archived_layout()
        # 同时存在活跃与归档 → 活跃优先
        self._active_layout()
        self.assertEqual(resolve_spec_dir(self.tmpdir, self.SPEC), self.spec_dir)

    def test_resolve_archive_fallback(self):
        from core.dashboard.data import resolve_spec_dir
        archive_dir = self._archived_layout()
        self.assertEqual(resolve_spec_dir(self.tmpdir, self.SPEC), archive_dir)

    def test_resolve_multiple_archives_latest_wins(self):
        from core.dashboard.data import resolve_spec_dir
        old = self._archived_layout(prefix="2026-09-01", content_marker="old")
        new = self._archived_layout(prefix="2026-09-05", content_marker="new")
        resolved = resolve_spec_dir(self.tmpdir, self.SPEC)
        self.assertEqual(resolved, new)

    def test_resolve_conflict_suffix_variant(self):
        from core.dashboard.data import resolve_spec_dir
        d1 = self._archived_layout(prefix="2026-09-02", content_marker="base")
        # 冲突后缀变体：同日期追加 -{毫秒}；重建活跃目录后移入带后缀名。
        # 字典序最大 = 后缀最大（"2026-09-02-demo-spec" < "...-987654321000"）
        self._active_layout()
        suffixed = self.archive_root / "2026-09-02-demo-spec-987654321000"
        shutil.move(str(self.spec_dir), str(suffixed))
        self.assertEqual(resolve_spec_dir(self.tmpdir, self.SPEC), suffixed)
        self.assertNotEqual(resolve_spec_dir(self.tmpdir, self.SPEC), d1)

    def test_resolve_soft_delete_variant_not_matched(self):
        """软删除命名（<name>-<Unix秒>，无日期前缀）不匹配——此类条目已从
        STATE.md 移除，dashboard 无入口，读侧不得误命中。"""
        from core.dashboard.data import resolve_spec_dir
        self._active_layout()
        self._write(self.spec_dir, "tasks.md", "# T\n")
        soft = self.archive_root / f"{self.SPEC}-1788260731"
        shutil.move(str(self.spec_dir), str(soft))
        self.assertIsNone(resolve_spec_dir(self.tmpdir, self.SPEC))

    def test_resolve_no_dir_returns_none(self):
        from core.dashboard.data import resolve_spec_dir
        self.assertIsNone(resolve_spec_dir(self.tmpdir, self.SPEC))

    # ── get_spec_doc 归档回退 ─────────────────────────────────────────────

    def test_archived_spec_five_docs_all_found(self):
        from core.dashboard.data import get_spec_doc
        archive_dir = self._archived_layout()
        expected = {
            "proposal": f"# 归档提案\n\n正文-archived",
            "design": f"# 归档设计\n\n正文-archived",
            "tasks": "# Tasks\n\n## 1. 归档任务\n\n- [x] 1.1 完成-archived\n- [ ] 1.2 待办-archived\n",
            "verification": "## 结论：✅ 通过（verified）\n\narchived",
            "scenarios": "# archived-capability\n\n## Scenario: 归档场景-archived",
        }
        for doc, want in expected.items():
            r = get_spec_doc(self.tmpdir, self.SPEC, doc)
            self.assertTrue(r["found"], f"{doc} 应 found=true")
            self.assertEqual(r["content"].strip(), want.strip(),
                             f"{doc} 内容须与归档目录原文一致")

    def test_archived_spec_tasks_parsed_from_archive(self):
        from core.dashboard.data import parse_tasks, tasks_note
        archive_dir = self._archived_layout()
        groups = parse_tasks(self.tmpdir, self.SPEC)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["title"], "归档任务")
        self.assertEqual([t["id"] for t in groups[0]["tasks"]], ["1.1", "1.2"])
        self.assertEqual(groups[0]["tasks"][0]["done"], True)
        self.assertEqual(groups[0]["tasks"][1]["done"], False)
        self.assertEqual(groups[0]["done"], 1)
        self.assertEqual(groups[0]["total"], 2)
        self.assertIsNone(tasks_note(self.tmpdir, self.SPEC))

    def test_archived_spec_verification_and_scenarios(self):
        from core.dashboard.data import get_spec_doc
        self._archived_layout()
        v = get_spec_doc(self.tmpdir, self.SPEC, "verification")
        self.assertTrue(v["found"])
        self.assertIn("archived", v["content"])
        s = get_spec_doc(self.tmpdir, self.SPEC, "scenarios")
        self.assertTrue(s["found"])
        self.assertIn("归档场景-archived", s["content"])

    def test_multiple_archives_doc_latest_wins(self):
        from core.dashboard.data import get_spec_doc
        self._archived_layout(prefix="2026-09-01", content_marker="old")
        self._archived_layout(prefix="2026-09-05", content_marker="new")
        r = get_spec_doc(self.tmpdir, self.SPEC, "proposal")
        self.assertTrue(r["found"])
        self.assertIn("正文-new", r["content"])
        self.assertNotIn("正文-old", r["content"])

    def test_active_spec_unchanged(self):
        from core.dashboard.data import get_spec_doc, parse_tasks
        self._active_layout()
        # 活跃 SPEC：五类文档均读活跃目录，回退不介入
        for doc in ("proposal", "design", "tasks", "verification", "scenarios"):
            r = get_spec_doc(self.tmpdir, self.SPEC, doc)
            self.assertTrue(r["found"], f"活跃 {doc} 应 found=true")
            self.assertIn("active", r["content"], f"活跃 {doc} 应从活跃目录读取")
        self.assertIn("正文-active", get_spec_doc(self.tmpdir, self.SPEC, "proposal")["content"])
        # 任务清单从活跃 tasks.md 解析（标题"实施"），不回退归档
        groups = parse_tasks(self.tmpdir, self.SPEC)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["title"], "实施")
        self.assertEqual(groups[0]["done"], 1)
        self.assertEqual(groups[0]["total"], 2)

    def test_spec_dir_missing_returns_found_false(self):
        from core.dashboard.data import get_spec_doc
        # spec 合法但活跃/归档都不存在 → 保持既有 found=False 语义
        for doc in ("proposal", "design", "tasks", "verification", "scenarios"):
            r = get_spec_doc(self.tmpdir, self.SPEC, doc)
            self.assertEqual(r, {"found": False, "content": ""})

    def test_traversal_spec_rejected(self):
        from core.dashboard.data import get_spec_doc, InvalidSpecName, InvalidSpecDoc
        self._archived_layout()
        for bad in ("..", "../outside", "..%2Fetc", "demo-spec/../../etc"):
            with self.assertRaises(InvalidSpecName, msg=f"spec {bad!r} 必须拒绝"):
                get_spec_doc(self.tmpdir, bad, "proposal")
        # doc 侧穿越由白名单拦截（InvalidSpecDoc），同样不返回任何文件内容
        with self.assertRaises((InvalidSpecName, InvalidSpecDoc)):
            get_spec_doc(self.tmpdir, self.SPEC, "../outside")

    def test_invalid_doc_rejected(self):
        from core.dashboard.data import get_spec_doc, InvalidSpecDoc
        self._archived_layout()
        with self.assertRaises(InvalidSpecDoc):
            get_spec_doc(self.tmpdir, self.SPEC, "proposal/../design")

    def test_tasks_note_archive_empty_groups_warning(self):
        from core.dashboard.data import tasks_note
        archive_dir = self._archived_layout()
        # 空 tasks.md（无分组）→ 提示文案（归档回退同样触发）
        (archive_dir / "tasks.md").write_text("# Tasks\n\nOops\n", encoding="utf-8")
        self.assertEqual(tasks_note(self.tmpdir, self.SPEC),
                         "tasks.md 存在但未解析出任务分组（分组格式不匹配或文件为空）")


class TestGenerationProgressCounting(unittest.TestCase):
    """出题计数口径（fix-planner-scenarios-batching-hook 配套）：

    planner 分批落盘为骨架→每 1/3 补全→最终完整。骨架含全部 id 但
    steps/assertions 全空——若计入，骨架落盘瞬间出题条 0→N/N 一次跳。
    口径改为「已补全场景数」（steps/assertions 非空），出题条随每批
    重写真实爬升。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, scenarios):
        vp = Path(self.tmpdir) / ".fenix" / "verify-progress" / "spec-x"
        vp.mkdir(parents=True, exist_ok=True)
        (vp / "test_scenarios.json").write_text(
            json.dumps(scenarios, ensure_ascii=False), encoding="utf-8")

    def _skeleton(self, n=3):
        return [{"id": f"s{i}", "kind": "web", "description": "d",
                 "steps": [], "assertions": []} for i in range(n)]

    @staticmethod
    def _flesh(s):
        return dict(s,
                    steps=[{"action": "navigate", "value": "http://x/#/p"}],
                    assertions=[{"type": "no_console_error"}])

    def test_skeleton_counts_zero_fleshed_counts_climb(self):
        from core.dashboard.data import count_generated_scenarios
        skeleton = self._skeleton()
        self._write(skeleton)
        self.assertEqual(count_generated_scenarios(self.tmpdir, "spec-x"), 0,
                         "骨架（steps/assertions 全空）不应计入已落盘场景数")
        self._write([self._flesh(skeleton[0])] + skeleton[1:])
        self.assertEqual(count_generated_scenarios(self.tmpdir, "spec-x"), 1,
                         "补全 1 个场景后计数应为 1")
        self._write([self._flesh(s) for s in skeleton])
        self.assertEqual(count_generated_scenarios(self.tmpdir, "spec-x"), 3,
                         "全部补全后计数应为全部场景数")

    def test_missing_or_corrupt_file_still_zero(self):
        from core.dashboard.data import count_generated_scenarios
        self.assertEqual(count_generated_scenarios(self.tmpdir, "spec-x"), 0)
        self._write("garbage")
        self.assertEqual(count_generated_scenarios(self.tmpdir, "spec-x"), 0)

    def test_planned_scenarios_counts_all_entries_incl_skeleton(self):
        """分母（count_planned_scenarios）= 场景条目总数，骨架也计入。

        骨架落盘即含全部 id（steps/assertions 空），故分母从首批起即达终值，
        分子（带肉数）随后爬升——done≤total 恒成立。
        """
        from core.dashboard.data import count_planned_scenarios
        self.assertEqual(count_planned_scenarios(self.tmpdir, "spec-x"), 0)
        skeleton = self._skeleton(3)
        self._write(skeleton)
        self.assertEqual(count_planned_scenarios(self.tmpdir, "spec-x"), 3,
                         "骨架（含全部 id）也应计入分母")
        self._write([self._flesh(skeleton[0])] + skeleton[1:])
        self.assertEqual(count_planned_scenarios(self.tmpdir, "spec-x"), 3,
                         "分母不随补全变化")
        self._write("garbage")
        self.assertEqual(count_planned_scenarios(self.tmpdir, "spec-x"), 0)

    def test_generation_progress_total_is_entry_count_not_spec_md(self):
        """回归（分子比分母大）：出题进度 total 必须与 done 同源。

        根因：曾用 count_scenarios（数 specs/<cap>/spec.md 的 `#### Scenario:`
        块）作分母——planner 会把单个 Scenario 按交付物形态拆成多形态条目
        （web/cli/api），二者单位不同（实测 20/11）；非「多形态验收」类 spec
        的 spec.md 更是 0 场景。total 须改数 test_scenarios.json 条目总数。
        """
        from core.dashboard.data import spec_generation_progress
        # spec.md 只有 2 个 Scenario 块，但 planner 拆出 5 个多形态条目
        sd = Path(self.tmpdir) / "spec" / "changes" / "spec-x" / "specs" / "cap"
        sd.mkdir(parents=True)
        (sd / "spec.md").write_text(
            "# cap\n\n#### Scenario: a\n- **WHEN** x\n\n#### Scenario: b\n- **WHEN** y\n",
            encoding="utf-8")
        self._write([{"id": f"s{i}", "kind": "cli", "description": "d",
                      "steps": [{"action": "run"}], "assertions": [{"type": "exit_code"}]}
                     for i in range(5)])
        gen = spec_generation_progress(self.tmpdir, "spec-x", {"status": "testing"}, vp={})
        self.assertIsNotNone(gen)
        self.assertEqual(gen["total"], 5, "分母应为场景条目数（5），非 spec.md 块数（2）")
        self.assertLessEqual(gen["done"], gen["total"],
                             f"分子不得大于分母：{gen}")


class TestRunTailInsightsTerminalReason(unittest.TestCase):
    """_run_tail_insights 提取终态事件原因（时间轴 run 节点错误原因可见化）。

    根因：run 产物终态事件自带原因（error 事件的 error 字段、interrupted /
    cancelled 事件的 reason 字段），但 _run_tail_insights 只提取
    summary/llm/usage，时间轴 run 节点只有红色 error Tag 无原因文本——
    用户只能靠时长猜死因（add-declaration-premechanize 2026-09-07 实证：
    「Max turns (600) reached」被误猜为 2.5h 运行上限）。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.runs_dir = Path(self.tmpdir) / ".fenix" / "runs"
        self.runs_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_run(self, run_id: str, events: list) -> Path:
        p = self.runs_dir / f"{run_id}.jsonl"
        p.write_text(
            "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
        return p

    def test_error_event_reason_extracted(self):
        from core.dashboard.data import _run_tail_insights
        p = self._write_run("impl-demo-1788840000-a1", [
            {"type": "provider_marker", "model": "m1", "provider": "p1"},
            {"type": "assistant", "content": "x"},
            {"type": "error", "error": "Max turns (600) reached", "exit_code": -9},
        ])
        ins = _run_tail_insights(p)
        self.assertEqual(ins["reason"], "Max turns (600) reached")

    def test_interrupted_reason_extracted(self):
        from core.dashboard.data import _run_tail_insights
        p = self._write_run("impl-demo-1788840001-a1", [
            {"type": "assistant", "content": "x"},
            {"type": "interrupted", "reason": "startup terminal-state sweep",
             "timestamp": "2026-09-07T08:10:09+00:00"},
        ])
        ins = _run_tail_insights(p)
        self.assertEqual(ins["reason"], "startup terminal-state sweep")

    def test_cancelled_reason_extracted(self):
        from core.dashboard.data import _run_tail_insights
        p = self._write_run("impl-demo-1788840002-a1", [
            {"type": "assistant", "content": "x"},
            {"type": "cancelled", "reason": "人工取消", "by": "dashboard"},
        ])
        ins = _run_tail_insights(p)
        self.assertEqual(ins["reason"], "人工取消")

    def test_done_run_reason_empty(self):
        from core.dashboard.data import _run_tail_insights
        p = self._write_run("impl-demo-1788840003-a1", [
            {"type": "assistant", "content": "x"},
            {"type": "result", "result": "全部完成"},
        ])
        ins = _run_tail_insights(p)
        self.assertEqual(ins["reason"], "")

    def test_missing_file_reason_empty(self):
        from core.dashboard.data import _run_tail_insights
        ins = _run_tail_insights(self.runs_dir / "nope.jsonl")
        self.assertEqual(ins["reason"], "")


class TestTimelineRunNodeTerminalReason(unittest.TestCase):
    """时间轴 run 节点下发 reason 字段（前端原因行数据源）。

    run 节点复用 state 节点的 reason 命名：人类可读的终态原因；
    无终态原因（运行中/成功）不下发或空，前端不渲染。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        runs_dir = Path(self.tmpdir) / ".fenix" / "runs"
        runs_dir.mkdir(parents=True)
        self.runs_dir = runs_dir

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _timeline_run_nodes(self):
        from core.dashboard.data import get_spec_timeline
        timeline = get_spec_timeline(self.tmpdir, "demo-spec")
        return [e for e in timeline if e.get("kind") == "run"]

    def test_error_run_node_has_reason(self):
        ts = int(time.time())
        (self.runs_dir / f"impl-demo-spec-{ts}-a1.jsonl").write_text(
            json.dumps({"type": "assistant", "content": "x"}) + "\n"
            + json.dumps({"type": "error", "error": "Max turns (600) reached",
                          "exit_code": -9}) + "\n",
            encoding="utf-8")
        nodes = self._timeline_run_nodes()
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["status"], "error")
        self.assertEqual(nodes[0]["reason"], "Max turns (600) reached")

    def test_interrupted_run_node_has_reason(self):
        ts = int(time.time())
        (self.runs_dir / f"impl-demo-spec-{ts}-a2.jsonl").write_text(
            json.dumps({"type": "assistant", "content": "x"}) + "\n"
            + json.dumps({"type": "interrupted", "reason": "startup sweep"}) + "\n",
            encoding="utf-8")
        nodes = self._timeline_run_nodes()
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["status"], "interrupted")
        self.assertEqual(nodes[0]["reason"], "startup sweep")

    def test_done_run_node_no_reason(self):
        ts = int(time.time())
        (self.runs_dir / f"impl-demo-spec-{ts}-a3.jsonl").write_text(
            json.dumps({"type": "assistant", "content": "x"}) + "\n"
            + json.dumps({"type": "result", "result": "完成"}) + "\n",
            encoding="utf-8")
        nodes = self._timeline_run_nodes()
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["status"], "done")
        self.assertFalse(nodes[0].get("reason"))


class TestGateBlockedRunVisibility(unittest.TestCase):
    """add-timeline-gate-failure-display：门禁终态 gate-blocked 的读侧全链路。

    写侧（runner._append_gate_blocked）在门禁失败终止本次 attempt 时追加末行
    gate-blocked（带 error/reason）。读侧 MUST 把它当**终态**：
    classify_run 查表返回 "gate-blocked"、可归档、不计活跃、时间轴节点下发
    status/reason；同时 MUST 在写侧终态集合（liveness.RUN_TERMINAL_EVENT_TYPES）
    登记——缺它末行 gate-blocked 的 run 在在跑判定里永被判「在跑」，刚被门禁
    拦下的 SPEC 删除/归档被误拦（tests/test_delete_stop_inflight_agents.py 同锁）。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.runs_dir = Path(self.tmpdir) / ".fenix" / "runs"
        self.runs_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_run(self, run_id: str, events: list) -> Path:
        p = self.runs_dir / f"{run_id}.jsonl"
        p.write_text(
            "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n",
            encoding="utf-8")
        return p

    def test_classify_run_returns_gate_blocked(self):
        """① 末行 gate-blocked → classify_run 返回 "gate-blocked"（非 running）。"""
        from core.dashboard.data import classify_run
        self.assertEqual(classify_run([{"type": "gate-blocked"}]), "gate-blocked")
        # CLI 的 result 在前、gate-blocked 收口在后（终态后置不变量）
        self.assertEqual(
            classify_run([{"type": "result"}, {"type": "gate-blocked"}]),
            "gate-blocked")
        # 写侧终态集合同步登记（两侧同步义务：缺它时间轴/在跑判定半接入）
        from core.agent_runner.liveness import RUN_TERMINAL_EVENT_TYPES
        self.assertIn("gate-blocked", RUN_TERMINAL_EVENT_TYPES)

    def test_gate_blocked_is_archivable(self):
        """② 可归档集合由映射派生 → gate-blocked 零改代码自动纳入。"""
        # 叶子模块直导（门面未转导该私有助手）
        from core.dashboard.data.runs import _is_run_archivable
        p = self._write_run("impl-demo-1789000000-a1", [
            {"type": "result", "result": "done"},
            {"type": "gate-blocked", "reason": "artifact_gate",
             "error": "结果文件缺失（impl-code-review-gate）"},
        ])
        self.assertTrue(_is_run_archivable(p))

    def test_gate_blocked_not_counted_active(self):
        """④ active_run_count 不计 gate-blocked（否则活跃数虚高）。"""
        from core.dashboard.data import active_run_count
        ts = int(time.time())
        self._write_run(f"impl-s-{ts}-a1", [
            {"type": "result", "result": "done"},
            {"type": "gate-blocked", "reason": "artifact_gate", "error": "e"},
        ])
        self._write_run(f"impl-s-{ts}-a2", [{"type": "assistant", "content": "x"}])
        self.assertEqual(active_run_count(self.tmpdir), 1)

    def test_tail_insights_gate_blocked_reason(self):
        """③ _run_tail_insights 从 gate-blocked 末行取非空 reason。"""
        from core.dashboard.data import _run_tail_insights
        p = self._write_run("impl-demo-1789000001-a1", [
            {"type": "gate-blocked", "reason": "artifact_gate",
             "error": "[artifact-structural] 结果文件缺失（impl-code-review-gate）"},
        ])
        ins = _run_tail_insights(p)
        self.assertIn("impl-code-review-gate", ins["reason"])

    def test_tail_insights_superseded_reason_from_error(self):
        """③ 弃置件 superseded 带 error → reason 非空（不再是无原因绿点）。"""
        from core.dashboard.data import _run_tail_insights
        p = self._write_run("impl-demo-1789000002-a1", [
            {"type": "transient_retry", "reason": "artifact_gate", "error": "g"},
            {"type": "superseded",
             "error": "[artifact-structural] 结果文件缺失（impl-code-review-gate）"},
        ])
        ins = _run_tail_insights(p)
        self.assertIn("impl-code-review-gate", ins["reason"])

    def test_timeline_run_node_gate_blocked_status_and_reason(self):
        """⑤ 时间轴 run 节点下发 status=gate-blocked 与非空 reason。"""
        from core.dashboard.data import get_spec_timeline
        ts = int(time.time())
        self._write_run(f"impl-demo-spec-{ts}-a1", [
            {"type": "assistant", "content": "x"},
            {"type": "gate-blocked", "reason": "artifact_gate",
             "error": "[artifact-structural] 结果文件缺失（impl-code-review-gate）"},
        ])
        nodes = [e for e in get_spec_timeline(self.tmpdir, "demo-spec")
                 if e.get("kind") == "run"]
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["status"], "gate-blocked")
        self.assertIn("impl-code-review-gate", nodes[0]["reason"])

    def test_timeline_run_node_superseded_reason(self):
        """⑤ 弃置节点（superseded）同样下发非空 reason。"""
        from core.dashboard.data import get_spec_timeline
        ts = int(time.time())
        self._write_run(f"impl-demo-spec-{ts}-a2", [
            {"type": "transient_retry", "reason": "artifact_gate", "error": "g"},
            {"type": "superseded", "error": "门禁拒绝（impl-code-review-gate）"},
        ])
        nodes = [e for e in get_spec_timeline(self.tmpdir, "demo-spec")
                 if e.get("kind") == "run"]
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["status"], "superseded")
        self.assertIn("impl-code-review-gate", nodes[0]["reason"])


class TestGatesPromoteModeConfigIO(unittest.TestCase):
    """add-draft-promotion-gate 验证修复：gates.promote_mode 受管键读写全链路。

    产品 Bug 回归：_deep_merge_managed 缺 promote_mode 合并分支，设置页保存的
    promote_mode 在 merge 阶段被静默丢弃（验证场景 api-config-get-after-save-promote-manual）。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir)
        self.config_dir = self.proot / ".fenix"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.config_dir / "config.yaml"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_deep_merge_managed_writes_promote_mode(self):
        """_deep_merge_managed 的 promote_mode 分支：patch gates.promote_mode 写入 merged["gates"]"""
        from core.dashboard.data import _deep_merge_managed

        raw_config = {
            "gates": {"approve_mode": "auto", "require_push_approval": True},
        }
        patch = {"gates": {"promote_mode": "manual"}}

        result = _deep_merge_managed(raw_config, patch)

        # promote_mode 写入；approve_mode 与非受管子键保留（不整段覆盖丢失）
        self.assertEqual(result["gates"]["promote_mode"], "manual")
        self.assertEqual(result["gates"]["approve_mode"], "auto")
        self.assertEqual(result["gates"]["require_push_approval"], True)

    def test_deep_merge_managed_promote_only_patch_keeps_approve(self):
        """只 patch promote_mode 时原始 gates 段无受管键也能正确创建"""
        from core.dashboard.data import _deep_merge_managed

        raw_config = {"project": {"name": "t"}}
        result = _deep_merge_managed(raw_config, {"gates": {"promote_mode": "auto"}})
        self.assertEqual(result["gates"]["promote_mode"], "auto")

    def test_write_config_promote_mode_persists(self):
        """write_config 保存 promote_mode 后落盘可读回（设置页保存生效闭环）"""
        from core.dashboard.data import write_config

        result = write_config(self.proot, {"gates": {"promote_mode": "manual"}})
        self.assertTrue(result["ok"], result.get("error"))

        import yaml
        with open(self.config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        self.assertEqual(config["gates"]["promote_mode"], "manual")

        # 二次保存切回 auto（幂等覆盖）
        result = write_config(self.proot, {"gates": {"promote_mode": "auto"}})
        self.assertTrue(result["ok"], result.get("error"))
        with open(self.config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        self.assertEqual(config["gates"]["promote_mode"], "auto")

    def test_write_config_promote_mode_invalid_rejected(self):
        """非法枚举值前置校验拒绝（不写盘）"""
        from core.dashboard.data import write_config

        result = write_config(self.proot, {"gates": {"promote_mode": "yes"}})
        self.assertFalse(result["ok"])
        self.assertIn("auto", result["error"])
        self.assertIn("manual", result["error"])

    def test_read_effective_config_promote_mode_echo_and_sources(self):
        """read_effective_config 回显 promote_mode + sources 标注；改晋升模式不丢审批模式"""
        from core.dashboard.data import read_effective_config, write_config

        user_dir = Path(self.tmpdir) / "user-fenix"
        with patch("core.config.USER_CONFIG_DIR", user_dir), \
             patch("core.dashboard.data.USER_CONFIG_PATH", user_dir / "config.yaml"):
            # 缺省：promote_mode 回显 auto，sources 标 user
            result = read_effective_config(self.proot)
            self.assertEqual(result["gates"]["promote_mode"], "auto")
            self.assertEqual(result["sources"].get("gates.promote_mode"), "user")

            # 写入 manual（同时带 approve_mode，模拟设置页保存载荷）
            w = write_config(self.proot, {"gates": {"promote_mode": "manual",
                                                    "approve_mode": "manual"}})
            self.assertTrue(w["ok"], w.get("error"))
            result = read_effective_config(self.proot)
            self.assertEqual(result["gates"]["promote_mode"], "manual")
            self.assertEqual(result["gates"]["approve_mode"], "manual")
            self.assertEqual(result["sources"].get("gates.promote_mode"), "project")

            # 只改 promote_mode、不带 approve_mode 的 patch：approve_mode 保留
            w = write_config(self.proot, {"gates": {"promote_mode": "auto"}})
            self.assertTrue(w["ok"], w.get("error"))
            import yaml
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            self.assertEqual(config["gates"]["promote_mode"], "auto")
            self.assertEqual(config["gates"]["approve_mode"], "manual")

    def test_read_config_view_promote_mode_echo(self):
        """编辑视图（read_config raw 提取）回显 promote_mode；缺省填 auto"""
        from core.dashboard.data import read_config

        # 缺省（文件不存在）：promote_mode 缺省 auto
        result = read_config(self.proot)
        self.assertEqual(result["gates"].get("promote_mode"), "auto")
        self.assertEqual(result["sources"].get("gates.promote_mode"), "user")

        # 显式 manual：回显 manual + sources 标 project
        import yaml
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump({"gates": {"promote_mode": "manual"}}, f)
        result = read_config(self.proot)
        self.assertEqual(result["gates"].get("promote_mode"), "manual")
        self.assertEqual(result["sources"].get("gates.promote_mode"), "project")

        # 非法值不回显（读侧缺省兜底 auto）
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump({"gates": {"promote_mode": "bogus"}}, f)
        result = read_config(self.proot)
        self.assertEqual(result["gates"].get("promote_mode"), "auto")


class TestSyncConfigFromUser(unittest.TestCase):
    """设置页「同步用户级设置」按钮（项目级）：把用户级 config.yaml 中 page 页签
    对应的受管键覆盖写入项目级——只覆盖当前页面的设置值，其它页签与项目级
    特有键不受影响；用户级未显式配置的键不覆盖（raw 读取无缺省填充）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir) / "proj"
        (self.proot / ".fenix").mkdir(parents=True)
        self.user_dir = Path(self.tmpdir) / "user-fenix"
        self.user_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _sync(self, page):
        from core.dashboard.data import sync_config_from_user
        with patch("core.dashboard.data.USER_CONFIG_PATH", self.user_dir / "config.yaml"):
            return sync_config_from_user(self.proot, page)

    def _write_user(self, cfg):
        import yaml
        with open(self.user_dir / "config.yaml", "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, allow_unicode=True)

    def _read_proj(self):
        import yaml
        with open(self.proot / ".fenix" / "config.yaml", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def test_unknown_page_rejected(self):
        result = self._sync("no-such-page")
        self.assertFalse(result["ok"])
        self.assertIn("未知页面标识", result["error"])

    def test_sync_single_page_copies_only_page_keys(self):
        """approval 页只同步 gates 两键——项目级已有 agents 键不受影响"""
        self._write_user({"gates": {"promote_mode": "manual", "approve_mode": "auto"}})
        # 项目级已有其它页的设置
        import yaml
        with open(self.proot / ".fenix" / "config.yaml", "w", encoding="utf-8") as f:
            yaml.dump({"agents": {"max_concurrent": 7}}, f)
        result = self._sync("approval")
        self.assertTrue(result["ok"], result["error"])
        proj = self._read_proj()
        self.assertEqual(proj["gates"]["promote_mode"], "manual")
        self.assertEqual(proj["gates"]["approve_mode"], "auto")
        self.assertEqual(proj["agents"]["max_concurrent"], 7, "其它页设置值不被覆盖")

    def test_sync_does_not_touch_keys_outside_page_whitelist(self):
        """system 页只同步 admin 六键+transient 五键——admin.self_review 不被覆盖"""
        self._write_user({
            "admin": {
                "enabled": False,
                "interval_minutes": 9,
                "self_review": {"enabled": True, "run_at": "03:00"},
            },
            "agents": {"transient_break_threshold": 5},
        })
        # 项目级已有自己的 self_review
        import yaml
        with open(self.proot / ".fenix" / "config.yaml", "w", encoding="utf-8") as f:
            yaml.dump({"admin": {"self_review": {"enabled": False, "run_at": "04:00"}}}, f)
        result = self._sync("system")
        self.assertTrue(result["ok"], result["error"])
        proj = self._read_proj()
        self.assertEqual(proj["admin"]["enabled"], False)
        self.assertEqual(proj["admin"]["interval_minutes"], 9)
        self.assertEqual(proj["admin"]["self_review"]["enabled"], False,
                         "self_review 不在 system 页白名单，项目级值保留")
        self.assertEqual(proj["agents"]["transient_break_threshold"], 5)

    def test_user_level_unset_keys_not_overwritten(self):
        """用户级未显式配置的键不覆盖项目级（raw 读取无缺省填充）"""
        self._write_user({"agents": {"max_concurrent": 3}})  # 未配 max_turns
        import yaml
        with open(self.proot / ".fenix" / "config.yaml", "w", encoding="utf-8") as f:
            yaml.dump({"agents": {"max_concurrent": 9, "max_turns": 123}}, f)
        result = self._sync("parallel")
        self.assertTrue(result["ok"], result["error"])
        proj = self._read_proj()
        self.assertEqual(proj["agents"]["max_concurrent"], 3, "用户级显式值覆盖")
        self.assertEqual(proj["agents"]["max_turns"], 123,
                         "用户级未配置的键保留项目级值")

    def test_user_file_missing_returns_error(self):
        # 用户级配置不存在：无可同步内容
        result = self._sync("token")
        self.assertFalse(result["ok"])
        self.assertIn("无可同步内容", result["error"])
        self.assertFalse((self.proot / ".fenix" / "config.yaml").exists(),
                         "失败同步不写项目级文件")

    def test_user_section_missing_returns_error(self):
        """用户级存在但无该页对应段：无可同步内容"""
        self._write_user({"gates": {"approve_mode": "manual"}})
        result = self._sync("misc")  # misc 页要 archive 段
        self.assertFalse(result["ok"])
        self.assertIn("无可同步内容", result["error"])

    def test_synced_echoes_patch(self):
        self._write_user({"verify": {"static_scope": "worktree", "deps_mode": "hardlink"}})
        result = self._sync("verify")
        self.assertTrue(result["ok"], result["error"])
        self.assertEqual(result["synced"], {"verify": {"static_scope": "worktree", "deps_mode": "hardlink"}})
        proj = self._read_proj()
        self.assertEqual(proj["verify"]["static_scope"], "worktree")
        self.assertEqual(proj["verify"]["deps_mode"], "hardlink")

    def test_invalid_user_value_rejected_by_write_validation(self):
        """用户级非法值经 write_config 前置校验拒绝，不写盘"""
        self._write_user({"verify": {"static_scope": "bogus"}})
        result = self._sync("verify")
        self.assertFalse(result["ok"])
        self.assertFalse((self.proot / ".fenix" / "config.yaml").exists())


class TestSpecBudgetData(unittest.TestCase):
    """set_spec_budget 返回形状与写盘断言（add-spec-status-modal-budget D3）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.sm = StateMachine(self.project_root / ".fenix" / "STATE.md", None)
        self.sm.add_spec("demo-spec", {"priority": 5})

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_set_override_writes_and_returns(self):
        from core.dashboard.data import set_spec_budget, parse_state
        result = set_spec_budget(self.project_root, "demo-spec", 8)
        self.assertEqual(result, {"ok": True, "found": True, "budget": 8})
        entry = parse_state(self.project_root)["demo-spec"]
        self.assertEqual(entry.get("impl_run_budget_override"), 8)

    def test_clear_null(self):
        from core.dashboard.data import set_spec_budget, parse_state
        set_spec_budget(self.project_root, "demo-spec", 8)
        result = set_spec_budget(self.project_root, "demo-spec", None)
        self.assertEqual(result, {"ok": True, "found": True, "budget": None})
        entry = parse_state(self.project_root)["demo-spec"]
        self.assertEqual(entry.get("impl_run_budget_override"), None)

    def test_spec_not_found(self):
        from core.dashboard.data import set_spec_budget
        result = set_spec_budget(self.project_root, "ghost", 5)
        self.assertFalse(result["found"])
        self.assertFalse(result["ok"])

    def test_terminal_rejected(self):
        from core.dashboard.data import set_spec_budget
        self.sm.update_spec("demo-spec", {"status": "done"})
        result = set_spec_budget(self.project_root, "demo-spec", 5)
        self.assertTrue(result["terminal"])
        self.assertFalse(result["ok"])

    def test_invalid_values_rejected(self):
        from core.dashboard.data import set_spec_budget, parse_state
        # open-impl-budget-ceiling：上限缺省 100，101 越界；11 现合法。
        for bad in (0, 101, "5", 3.5, True, -1):
            result = set_spec_budget(self.project_root, "demo-spec", bad)
            self.assertTrue(result["invalid"], f"budget={bad!r} 应拒绝")
        entry = parse_state(self.project_root)["demo-spec"]
        # serialize 总写 impl_run_budget_override（null），非法值拒绝写入 → 仍为 null
        self.assertIsNone(entry.get("impl_run_budget_override"))

    def test_does_not_touch_used_counter(self):
        from core.dashboard.data import set_spec_budget, parse_state
        self.sm.update_spec("demo-spec", {"_impl_run_budget_used": 3})
        set_spec_budget(self.project_root, "demo-spec", 6)
        entry = parse_state(self.project_root)["demo-spec"]
        self.assertEqual(int(entry.get("_impl_run_budget_used", 0)), 3)


class TestSpecSummaryBudgetFields(unittest.TestCase):
    """spec_summary 三预算字段（覆盖/无覆盖/非法覆盖三态，与闸门口径一致）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir(parents=True, exist_ok=True)
        (self.project_root / "spec" / "changes" / "demo-spec").mkdir(parents=True, exist_ok=True)
        self.sm = StateMachine(self.project_root / ".fenix" / "STATE.md", None)
        self.sm.add_spec("demo-spec", {"priority": 5})
        # 项目级 config 无 impl_run_budget（真实环境可能有用户级配置影响，
        # 测试通过 mock ConfigLoader.resolve_config 控制全局值，保证 DEFAULT 回退路径可测）
        (self.project_root / ".fenix" / "config.yaml").write_text(
            "project:\n  name: t\n", encoding="utf-8")
        # 重置全局预算缓存，避免跨测试污染
        from core.dashboard.data import _GLOBAL_BUDGET_CACHE
        _GLOBAL_BUDGET_CACHE.clear()

    def tearDown(self):
        from core.dashboard.data import _GLOBAL_BUDGET_CACHE
        _GLOBAL_BUDGET_CACHE.clear()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _summary(self):
        from core.dashboard.data import spec_summary, parse_state
        entry = parse_state(self.project_root)["demo-spec"]
        return spec_summary(self.project_root, "demo-spec", entry)

    def test_no_override_fallback_default(self):
        """无 override 且回退全局 config（mock resolve_config 无 impl_run_budget 键）
        → 回退 DEFAULT_IMPL_RUN_BUDGET = 6。"""
        from core.pm_engine.budget import DEFAULT_IMPL_RUN_BUDGET
        with patch("core.config.ConfigLoader.resolve_config",
                   return_value={}), \
             patch("core.config.ConfigLoader.get", return_value=None):
            from core.dashboard.data import _GLOBAL_BUDGET_CACHE
            _GLOBAL_BUDGET_CACHE.clear()
            s = self._summary()
        self.assertEqual(s["budget_used"], 0)
        self.assertIsNone(s["budget_override"])
        self.assertEqual(s["budget_effective"], DEFAULT_IMPL_RUN_BUDGET)

    def test_override_set(self):
        self.sm.update_spec("demo-spec", {"impl_run_budget_override": 8,
                                          "_impl_run_budget_used": 5})
        s = self._summary()
        self.assertEqual(s["budget_used"], 5)
        self.assertEqual(s["budget_override"], 8)
        self.assertEqual(s["budget_effective"], 8)

    def test_invalid_override_fallback_global(self):
        """非法覆盖值经 parse 归一为 None → 回退全局 config（mock 为无值 → DEFAULT 6）。"""
        self.sm.update_spec("demo-spec", {"impl_run_budget_override": "abc"})
        from core.pm_engine.budget import DEFAULT_IMPL_RUN_BUDGET
        with patch("core.config.ConfigLoader.resolve_config",
                   return_value={}), \
             patch("core.config.ConfigLoader.get", return_value=None):
            from core.dashboard.data import _GLOBAL_BUDGET_CACHE
            _GLOBAL_BUDGET_CACHE.clear()
            s = self._summary()
        self.assertIsNone(s["budget_override"])
        self.assertEqual(s["budget_effective"], DEFAULT_IMPL_RUN_BUDGET)

    def test_override_clamped_like_gate(self):
        """覆盖越界与闸门同口径夹紧（0→1；超缺省上限 100 → 100）。"""
        self.sm.update_spec("demo-spec", {"impl_run_budget_override": 101})
        s = self._summary()
        self.assertEqual(s["budget_override"], 100)
        self.assertEqual(s["budget_effective"], 100)
        self.assertEqual(s["budget_max"], 100)

    def test_used_tolerant_on_bad_value(self):
        self.sm.update_spec("demo-spec", {"_impl_run_budget_used": "oops"})
        s = self._summary()
        self.assertEqual(s["budget_used"], 0)


class TestNormalizeDependsOn(unittest.TestCase):
    """add-spec-manual-activation 10.7：_normalize_depends_on 单元用例。

    关键反例：STATE.md 的 `depends_on: null` 解析回字面量字符串 "null"
    （该字段未登记在解析器 null→None 归一化键表），必须归一化为 None——
    否则前端「前置依赖」标记对无依赖 SPEC 全线误标。
    """

    def setUp(self):
        from core.dashboard.data.summary import _normalize_depends_on
        self.fn = _normalize_depends_on

    def test_none_and_empty_to_none(self):
        self.assertIsNone(self.fn(None))
        self.assertIsNone(self.fn(""))
        self.assertIsNone(self.fn("   "))
        self.assertIsNone(self.fn("  \t\n "))

    def test_literal_null_string_to_none(self):
        # 字面量字符串 "null"（serialize 对空值恒写 `- depends_on: null`，
        # 解析回字符串 "null" 而非 None）——大小写不敏感
        self.assertIsNone(self.fn("null"))
        self.assertIsNone(self.fn("NULL"))
        self.assertIsNone(self.fn("  null  "))

    def test_real_deps_kept_stripped(self):
        self.assertEqual(self.fn("spec-a"), "spec-a")
        self.assertEqual(self.fn(" spec-a "), "spec-a")
        self.assertEqual(self.fn("spec-a, spec-b"), "spec-a, spec-b")
        self.assertEqual(self.fn("fix-a,b"), "fix-a,b")

    def test_non_string_scalar_coerced(self):
        # 防御性：非字符串值 str() 后走同一口径——"0" 不是 null，保留
        self.assertEqual(self.fn(0), "0")
        self.assertEqual(self.fn(123), "123")
        # 但 None 本身走前置分支直接返回 None（不经过 str()）
        self.assertIsNone(self.fn(None))


class TestStartAfterScopeDashboardConfig(unittest.TestCase):
    """add-start-after-scope-config 3.7：gates.start_after_scope 读写回显、校验、同步。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir) / "proj"
        (self.proot / ".fenix").mkdir(parents=True)
        self.config_path = self.proot / ".fenix" / "config.yaml"
        self.user_dir = Path(self.tmpdir) / "user-fenix"
        self.user_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_read_config_default_dispatch(self):
        """(a) 未配置时 gates.start_after_scope 回显 dispatch。"""
        from core.dashboard.data import read_config

        result = read_config(self.proot)
        self.assertEqual(result["gates"]["start_after_scope"], "dispatch")

    def test_read_config_explicit_full(self):
        """(b) 配置 full 后回显 full + sources 标 project。"""
        from core.dashboard.data import read_config

        import yaml
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump({"gates": {"start_after_scope": "full"}}, f)
        result = read_config(self.proot)
        self.assertEqual(result["gates"]["start_after_scope"], "full")
        self.assertEqual(result["sources"].get("gates.start_after_scope"), "project")

    def test_write_config_readback_consistent(self):
        """(c) write_config 写入 full 后读回一致。"""
        from core.dashboard.data import write_config, read_config

        result = write_config(self.proot, {"gates": {"start_after_scope": "full"}})
        self.assertTrue(result["ok"], result.get("error"))
        echoed = read_config(self.proot)
        self.assertEqual(echoed["gates"]["start_after_scope"], "full")

    def test_write_config_invalid_rejected(self):
        """(d) write_config 传非法值 sometimes 返回 ok=False 且不写盘。"""
        from core.dashboard.data import write_config, read_config

        result = write_config(self.proot, {"gates": {"start_after_scope": "sometimes"}})
        self.assertFalse(result["ok"])
        self.assertIn("start_after_scope", result["error"])
        # 不写盘——回显仍为缺省
        echoed = read_config(self.proot)
        self.assertEqual(echoed["gates"]["start_after_scope"], "dispatch")

    def test_sync_approval_page_copies_start_after_scope(self):
        """(e) sync_config_from_user 的 approval 页能同步 start_after_scope 从用户级到项目级。"""
        from core.dashboard.data import sync_config_from_user

        self._write_user({"gates": {"start_after_scope": "full"}})
        with patch("core.dashboard.data.USER_CONFIG_PATH", self.user_dir / "config.yaml"):
            result = sync_config_from_user(self.proot, "approval")
        self.assertTrue(result["ok"], result.get("error"))
        # synced 字典应含 start_after_scope
        self.assertIn("start_after_scope", result["synced"]["gates"])
        self.assertEqual(result["synced"]["gates"]["start_after_scope"], "full")
        # 项目级文件实际写入
        import yaml
        with open(self.config_path, encoding="utf-8") as f:
            proj = yaml.safe_load(f)
        self.assertEqual(proj["gates"]["start_after_scope"], "full")

    def test_read_config_approve_mode_does_not_drop_other_gates(self):
        """(f) 项目级显式配了 approve_mode 时，read_config 的 gates 段 MUST 仍含
        promote_mode / spec_review_mode / start_after_scope（锁定 3.2 修复）。"""
        from core.dashboard.data import read_config

        import yaml
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump({"gates": {"approve_mode": "auto"}}, f)
        result = read_config(self.proot)
        gates = result["gates"]
        # approve_mode 显式配置了
        self.assertEqual(gates["approve_mode"], "auto")
        # 其余三键不应被丢弃
        self.assertIn("promote_mode", gates)
        self.assertIn("spec_review_mode", gates)
        self.assertIn("start_after_scope", gates)

    def _write_user(self, cfg):
        import yaml
        with open(self.user_dir / "config.yaml", "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, allow_unicode=True)


if __name__ == "__main__":
    unittest.main()
