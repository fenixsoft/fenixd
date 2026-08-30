"""add-implementer-deliverable-gate 单元测试与集成测试。

覆盖：
1. deliverables.extract_paths 纯函数（真实 v2-config-page 夹具 + 边界）
2. PMEngine 收工守卫（缺件阻断 / 全存在放行 / 无路径跳过 / 3 次封顶 blocked）
3. 守卫零成本断言（无 LLM/测试/网络调用，仅文件 stat）
4. agent_runner 重派 prompt 注入上轮 error（D4）
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent_runner import AgentRunner, AgentRunResult
from core.deliverables import extract_paths
from core.pm_engine import PMEngine
from core.state_machine import StateMachine

REPO_ROOT = Path(__file__).resolve().parent.parent


class _FakeLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass

    def debug(self, *a, **k):
        pass


# ── deliverables.extract_paths 纯函数 ──────────────────────────────────────

class TestExtractPaths(unittest.TestCase):
    def test_extract_from_real_v2_config_page_fixture(self):
        """从真实事故现场文档提取出 config.json 等预期路径。"""
        spec_dir = REPO_ROOT / "openspec" / "changes" / "v2-config-page"
        paths = extract_paths(spec_dir)
        # proposal.md 与 tasks.md 均声明了 core/dashboard/static/v2/pages/config.json
        self.assertIn("core/dashboard/static/v2/pages/config.json", paths)
        # 去重：proposal 与 tasks 各声明一次，仅出现一次
        self.assertEqual(
            paths.count("core/dashboard/static/v2/pages/config.json"), 1
        )

    def test_extract_backtick_and_codeblock(self):
        """反引号包裹与代码块均能提取，且保留前缀过滤。"""
        d = Path(tempfile.mkdtemp())
        try:
            (d / "tasks.md").write_text(
                "# T\n"
                "- [ ] 1.1 写 `core/foo.py` 与 `tests/test_foo.py`\n"
                "```\ncore/bar.py\nscripts/run.sh\n/core/abs.py\ncore/dir/\n```\n",
                encoding="utf-8",
            )
            paths = extract_paths(d)
            self.assertIn("core/foo.py", paths)
            self.assertIn("tests/test_foo.py", paths)
            self.assertIn("core/bar.py", paths)
            self.assertIn("scripts/run.sh", paths)
            # 绝对路径被排除
            self.assertNotIn("/core/abs.py", paths)
            # 目录条目（以 / 结尾）被排除
            self.assertNotIn("core/dir/", paths)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_extract_path_label_line(self):
        """「路径：」前缀行提取。"""
        d = Path(tempfile.mkdtemp())
        try:
            (d / "proposal.md").write_text(
                "路径: core/a.py core/b.py\n", encoding="utf-8"
            )
            paths = extract_paths(d)
            self.assertIn("core/a.py", paths)
            self.assertIn("core/b.py", paths)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_empty_doc_returns_empty(self):
        """空文档/无路径文档返回空列表。"""
        d = Path(tempfile.mkdtemp())
        try:
            (d / "tasks.md").write_text(
                "# No deliverables here\n- 只是一些说明文字，无显式路径\n",
                encoding="utf-8",
            )
            self.assertEqual(extract_paths(d), [])
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_nonexistent_dir_returns_empty(self):
        self.assertEqual(extract_paths(Path("/nonexistent_xyz_123")), [])

    def test_wildcard_excluded(self):
        """通配符路径不计入（是目录批量描述，不是单交付物）。"""
        d = Path(tempfile.mkdtemp())
        try:
            (d / "tasks.md").write_text(
                "- 覆盖 `core/*.py`\n- 单文件 `core/real.py`\n", encoding="utf-8"
            )
            paths = extract_paths(d)
            self.assertIn("core/real.py", paths)
            self.assertNotIn("core/*.py", paths)
        finally:
            shutil.rmtree(d, ignore_errors=True)


# ── PMEngine 收工守卫集成 ──────────────────────────────────────────────────

class _GateFixture(unittest.TestCase):
    """真实 StateMachine + mock runner/worktree_manager，复刻 _run_agent_worker 成功分支。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.project_root = self.tmpdir
        (self.project_root / ".fenix").mkdir(exist_ok=True)
        self.logger = _FakeLogger()
        self.sm = StateMachine(self.project_root / "STATE.md", self.logger)
        self.runner = mock.MagicMock()
        self.runner.worktree_manager = mock.MagicMock()
        self.config = {}
        self.engine = PMEngine(self.sm, self.runner, self.config,
                               self.project_root, self.logger)
        self.wm = self.runner.worktree_manager

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def make_ready_spec(self, name="s1"):
        self.sm.add_spec(name, {"priority": 5})
        self.sm.transition(name, "ready")
        return self.sm.read_one(name)

    def make_result(self, branch="fenix/s1", run_id="run-1"):
        return AgentRunResult(run_id, "s1", "implementer",
                              success=True, duration_seconds=1.0, branch=branch)

    def write_spec_dir(self, name, tasks_text):
        spec_dir = self.project_root / "openspec" / "changes" / name
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "tasks.md").write_text(tasks_text, encoding="utf-8")
        return spec_dir

    def run_gate(self, branch="fenix/s1"):
        """直接驱动守卫逻辑（等价于 _run_agent_worker 成功分支内的 guard 调用）。"""
        result = self.make_result(branch=branch)
        return self.engine._deliverable_gate_missing("s1", result)


class TestDeliverableGate(_GateFixture):
    def test_missing_blocks_no_merge(self):
        """缺件：不 merge、状态 ready、error 含缺件清单；重派实现。"""
        self.make_ready_spec("s1")
        self.write_spec_dir("s1", "- [ ] 1.1 写 `core/foo.py`\n")
        # 分支 HEAD 不含该文件
        self.wm.file_exists_on_branch.return_value = False

        missing = self.engine._deliverable_gate_missing("s1", self.make_result())
        self.assertEqual(missing, ["core/foo.py"])

        # 复刻成功分支守卫处置：更新 STATE 并重派
        spec_entry = self.sm.read_one("s1") or {}
        retries = int(spec_entry.get("_retry_count", 0) or 0) + 1
        self.sm.update_spec("s1", {
            "status": "ready", "error": "交付物守卫：缺件 [core/foo.py]（第 1 次）",
            "_retry_count": retries,
        })
        self.engine._enqueue_front("s1", "implementer")

        entry = self.sm.read_one("s1")
        self.assertEqual(entry["status"], "ready")
        self.assertIn("交付物守卫", entry["error"])
        self.assertIn("core/foo.py", entry["error"])
        self.assertEqual(self.engine._run_queue[-1][1:3], ("s1", "implementer"))

    def test_all_present_passes(self):
        """全部存在：守卫放行（返回空缺件清单）。"""
        self.make_ready_spec("s1")
        self.write_spec_dir("s1", "- [ ] 1.1 写 `core/foo.py`\n")
        self.wm.file_exists_on_branch.return_value = True
        self.assertEqual(self.run_gate(), [])

    def test_no_path_spec_skipped(self):
        """无路径 SPEC：守卫跳过（返回空），行为与守卫上线前一致。"""
        self.make_ready_spec("s1")
        self.write_spec_dir("s1", "# 纯说明，无显式交付路径\n- 做点事\n")
        # 即便 file_exists 返回 False，也应跳过（不校验）
        self.wm.file_exists_on_branch.return_value = False
        self.assertEqual(self.run_gate(), [])

    def test_three_strikes_blocked(self):
        """3 次封顶：连续缺件重派，第 3 次 blocked + 升级告警。"""
        self.make_ready_spec("s1")
        self.write_spec_dir("s1", "- [ ] 1.1 写 `core/foo.py`\n")
        self.wm.file_exists_on_branch.return_value = False
        max_r = self.engine._get_config("agents.max_retries", 3)

        for i in range(1, max_r + 1):
            missing = self.engine._deliverable_gate_missing("s1", self.make_result())
            self.assertEqual(missing, ["core/foo.py"])
            spec_entry = self.sm.read_one("s1") or {}
            retries = int(spec_entry.get("_retry_count", 0) or 0) + 1
            updates = {"status": "ready", "_retry_count": retries,
                       "error": f"交付物守卫：缺件 [core/foo.py]（第 {retries} 次）"}
            if retries >= max_r:
                updates["status"] = "blocked"
                updates["tester_run"] = None
                updates["error"] = (f"交付物守卫连续 {max_r} 次缺件 [core/foo.py] "
                                    f"— 已 blocked，需人工检查任务书声明与实际落地差异")
            self.sm.update_spec("s1", updates)
            if updates["status"] != "blocked":
                self.engine._enqueue_front("s1", "implementer")

        entry = self.sm.read_one("s1")
        self.assertEqual(entry["status"], "blocked")
        self.assertIn("交付物守卫", entry["error"])
        self.assertEqual(int(entry["_retry_count"]), max_r)

    def test_missing_is_zero_cost(self):
        """守卫零成本断言：仅调用 file_exists_on_branch（文件 stat），无 LLM/测试/网络。"""
        self.make_ready_spec("s1")
        self.write_spec_dir("s1", "- [ ] 1.1 写 `core/foo.py` 和 `tests/t.py`\n")
        # 仅允许 worktree_manager.file_exists_on_branch 被调用；任何其它 subprocess/网络/LLM 调用即失败
        self.wm.file_exists_on_branch.return_value = False
        with mock.patch.object(self.engine, "_read_implementer_result", return_value=None), \
             mock.patch("core.pm_engine.subprocess.run", side_effect=AssertionError("unexpected subprocess")):
            missing = self.engine._deliverable_gate_missing("s1", self.make_result())
        self.assertEqual(set(missing), {"core/foo.py", "tests/t.py"})
        # 恰好为每个声明路径调用一次存在性检查
        self.assertEqual(self.wm.file_exists_on_branch.call_count, 2)


# ── agent_runner 重派 prompt 注入（D4） ────────────────────────────────────

class TestImplementerPromptErrorInjection(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.project_root = self.tmpdir
        (self.project_root / ".fenix").mkdir(exist_ok=True)
        self.logger = _FakeLogger()
        self.sm = StateMachine(self.project_root / "STATE.md", self.logger)
        self.wm = mock.MagicMock()
        self.runner = AgentRunner.__new__(AgentRunner)
        self.runner.logger = self.logger
        self.runner.state_machine = self.sm
        self.runner.project_root = self.project_root
        self.runner.worktree_manager = self.wm

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_no_error_no_injection(self):
        self.sm.add_spec("s1", {"priority": 5})
        prompt = self.runner._build_prompt("s1", "implementer")
        self.assertNotIn("Previous run error", prompt)

    def test_deliverable_guard_error_injected(self):
        self.sm.add_spec("s1", {"priority": 5})
        self.sm.update_spec("s1", {
            "error": "交付物守卫：缺件 [core/foo.py] — 不合并不推进，重派实现补齐（第 1 次）",
        })
        prompt = self.runner._build_prompt("s1", "implementer")
        self.assertIn("Previous run error", prompt)
        self.assertIn("交付物守卫：缺件 [core/foo.py]", prompt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
