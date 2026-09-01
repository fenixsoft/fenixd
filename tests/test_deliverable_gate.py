"""add-implementer-deliverable-gate 单元测试与集成测试。

覆盖：
1. deliverables.extract_paths 纯函数（真实 v2-config-page 夹具 + 边界）
2. PMEngine 收工守卫（缺件阻断 / 全存在放行 / 无路径跳过 / 3 次封顶 blocked）
3. 守卫零成本断言（无 LLM/测试/网络调用，仅文件 stat）
4. agent_runner 重派 prompt 注入上轮 error（D4）
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent_runner import AgentRunner, AgentRunResult
from core.deliverables import extract_paths, extract_paths_typed, \
    normalize_check_path
from core.pm_engine import PMEngine
from core.state_machine import StateMachine
from core.worktree_manager import WorktreeManager

REPO_ROOT = Path(__file__).resolve().parent.parent

# add-deliverable-extractor-semantics 回归夹具（真实分支 + 真实 SPEC 文档）
INTERACTION_CONTRACT_SPEC = "add-interaction-contract-and-per-assert-triage"
INTERACTION_CONTRACT_BRANCH = "fenix/add-interaction-contract-and-per-assert-triage-1788091910"
INTERACTION_CONTRACT_REFERENCES = [
    ".fenix/core/agent_runner.py",
    ".fenix/core/verify_scenarios.py",
    ".fenix/core/verdict_check.py",
    ".fenix/core/verify_report.py",
]


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

    def test_template_placeholder_excluded(self):
        """``<...>`` 占位符路径不计入（模式描述不是字面路径，守卫按名校验必缺件）。

        fix-admin-run-blocks-mainloop 事故（2026-09-01）：tasks 勾选行上的
        ``.fenix/admin_disposition-<run_id>.json`` 被判为交付物，run 成功仍被
        缺件拦截并无限重派。
        """
        d = Path(tempfile.mkdtemp())
        try:
            (d / "tasks.md").write_text(
                "- [ ] 1.1 `core/real.py` 参数化（路径 `.fenix/x-<run_id>.json`）\n"
                "- [ ] 1.2 `core/other.py` 改为 `.fenix/y-<n>.json` 模板\n",
                encoding="utf-8",
            )
            typed = extract_paths_typed(d)
            self.assertEqual(
                typed["deliverables"], ["core/real.py", "core/other.py"]
            )
            self.assertNotIn(".fenix/x-<run_id>.json", typed["deliverables"])
            self.assertNotIn(".fenix/y-<n>.json", typed["deliverables"])
            # 占位符既非交付物也非引用：整体不参与校验
            self.assertNotIn(".fenix/x-<run_id>.json", typed["references"])
        finally:
            shutil.rmtree(d, ignore_errors=True)


# ── deliverables.extract_paths_typed 语境分类（add-deliverable-extractor-semantics） ──

class TestExtractPathsTyped(unittest.TestCase):
    def test_reference_context_not_deliverable_real_fixture(self):
        """真实样本（interaction-contract tasks.md）：头部「实现依据」段 4 路径归 references。"""
        spec_dir = REPO_ROOT / "openspec" / "changes" / INTERACTION_CONTRACT_SPEC
        typed = extract_paths_typed(spec_dir)
        for ref in INTERACTION_CONTRACT_REFERENCES:
            self.assertIn(ref, typed["references"])
            self.assertNotIn(ref, typed["deliverables"])
        # 该 SPEC 全部勾选项均为既有文件扩展，无新建交付物声明
        self.assertEqual(typed["deliverables"], [])

    def test_deliverable_context_still_extracted(self):
        """tasks 勾选行与「新增」动词行 → deliverables。"""
        d = Path(tempfile.mkdtemp())
        try:
            (d / "tasks.md").write_text(
                "# T\n"
                "- [ ] 1.1 新建 `core/foo.py`\n"
                "## 2\n"
                "创建 `tests/test_foo.py` 并补齐用例\n",
                encoding="utf-8",
            )
            typed = extract_paths_typed(d)
            self.assertEqual(typed["deliverables"],
                             ["core/foo.py", "tests/test_foo.py"])
            self.assertEqual(typed["references"], [])
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_undecided_in_tasks_conservative_deliverable(self):
        """无法判定（tasks 正文叙述行）→ 保守归 deliverables（宁误拦不漏放）。"""
        d = Path(tempfile.mkdtemp())
        try:
            (d / "tasks.md").write_text(
                "# T\n## 1\n- 落点见 `core/bar.py`\n",
                encoding="utf-8",
            )
            typed = extract_paths_typed(d)
            self.assertIn("core/bar.py", typed["deliverables"])
            self.assertNotIn("core/bar.py", typed["references"])
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_undecided_in_proposal_defaults_reference(self):
        """proposal 叙述性段落（无交付动词）→ references；仅「交付/新增」语境归 deliverables。"""
        d = Path(tempfile.mkdtemp())
        try:
            (d / "proposal.md").write_text(
                "叙述：`.fenix/x` 按 `x` 在分支校验。\n"
                "- 新增 `core/deliv.py`：正式化行为\n",
                encoding="utf-8",
            )
            typed = extract_paths_typed(d)
            self.assertIn(".fenix/x", typed["references"])
            self.assertEqual(typed["deliverables"], ["core/deliv.py"])
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_spec_scenario_examples_are_references(self):
        """能力 spec 文档 Scenario 中的示例路径（含「新建」动词行）归 references。

        回归：本变更能力 spec 的场景示例 `.fenix/x` / `core/foo.py` 曾被当作
        交付物，导致守卫连续误判缺件（2026-08-30 第 2 次重派根因）。
        """
        d = Path(tempfile.mkdtemp())
        (d / "specs").mkdir()
        try:
            (d / "specs" / "cap.md").write_text(
                "# cap 增量规格\n\n"
                "### Requirement: X\n"
                "系统 MUST 处理 `.fenix/` 前缀路径。\n\n"
                "#### Scenario: 交付语境仍阻断\n"
                "- **GIVEN** tasks 勾选行声明新建 `core/foo.py` 而分支中不存在\n"
                "- **WHEN** 守卫校验\n",
                encoding="utf-8",
            )
            typed = extract_paths_typed(d)
            self.assertIn("core/foo.py", typed["references"])
            self.assertNotIn("core/foo.py", typed["deliverables"])
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_normalize_check_path(self):
        """`.fenix/` 前缀归一化（正式化热修 4461231）。"""
        self.assertEqual(normalize_check_path(".fenix/core/x.py"), "core/x.py")
        self.assertEqual(normalize_check_path(".fenix/x"), "x")
        # 无前缀 / 空串 / 目录形态原样返回
        self.assertEqual(normalize_check_path("core/x.py"), "core/x.py")
        self.assertEqual(normalize_check_path(""), "")
        self.assertEqual(normalize_check_path(".fenix/"), ".fenix/")

    def test_compat_wrapper_union_unchanged(self):
        """旧 extract_paths = deliverables + references 拼接去重（既有调用方不破坏）。"""
        d = Path(tempfile.mkdtemp())
        try:
            (d / "tasks.md").write_text(
                "# T\n"
                "实现依据：`.fenix/core/base.py`（既有框架文件）\n"
                "## 1\n"
                "- [ ] 1.1 写 `core/foo.py`\n",
                encoding="utf-8",
            )
            typed = extract_paths_typed(d)
            self.assertEqual(extract_paths(d),
                             typed["deliverables"] + typed["references"])
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
        return self.engine._verification._deliverable_gate_missing("s1", result)


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
        self.engine._dispatcher._enqueue_front("s1", "implementer")

        entry = self.sm.read_one("s1")
        self.assertEqual(entry["status"], "ready")
        self.assertIn("交付物守卫", entry["error"])
        self.assertIn("core/foo.py", entry["error"])
        self.assertEqual(self.engine._dispatcher._run_queue[-1][1:3], ("s1", "implementer"))

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
                self.engine._dispatcher._enqueue_front("s1", "implementer")

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


# ── PMEngine 收工守卫：typed 提取 + 归一化 + 引用软校验 ────────────────────

class _CapturingLogger(_FakeLogger):
    def __init__(self):
        self.warnings = []

    def warning(self, *args, **kwargs):
        self.warnings.append((args, kwargs))


_REFERENCE_ONLY_TASKS = (
    "# Tasks: s1\n\n"
    "实现依据（实施 agent 必读）：\n"
    "- 现状代码：`.fenix/core/agent_runner.py` planner prompt\n"
    "- 上游依赖：`.fenix/core/verify_scenarios.py`\n\n"
    "## 1. 任务\n\n"
    "- [ ] 1.1 扩展既有模块行为\n"
)


class TestDeliverableGateTyped(_GateFixture):
    def test_reference_context_does_not_block(self):
        """引用语境（4 路径头部说明段）不产生缺件：不阻断、不重派。"""
        self.make_ready_spec("s1")
        self.write_spec_dir("s1", _REFERENCE_ONLY_TASKS)
        # 引用路径在分支中不存在也照常放行
        self.wm.file_exists_on_branch.return_value = False
        self.assertEqual(self.run_gate(), [])

    def test_reference_missing_audits_only(self):
        """引用缺失仅记审计日志（含 spec 与路径清单），不产生缺件/重派/状态变更。"""
        self.make_ready_spec("s1")
        self.write_spec_dir("s1", _REFERENCE_ONLY_TASKS)
        self.wm.file_exists_on_branch.return_value = False
        capturing = _CapturingLogger()
        self.engine.logger = capturing

        result = self.engine._deliverable_gate_missing("s1", self.make_result())

        self.assertEqual(result, [])
        self.assertEqual(len(capturing.warnings), 1)
        args, kwargs = capturing.warnings[0]
        self.assertEqual(args[0], "deliverable-reference-missing")
        ctx = kwargs.get("context") or {}
        self.assertEqual(ctx.get("spec"), "s1")
        self.assertEqual(sorted(ctx.get("missing_references") or []),
                         [".fenix/core/agent_runner.py",
                          ".fenix/core/verify_scenarios.py"])
        # 状态未被改动、未重派
        entry = self.sm.read_one("s1")
        self.assertEqual(entry["status"], "ready")
        self.assertEqual(self.engine._dispatcher._run_queue, [])

    def test_deliverable_missing_still_blocks_with_references(self):
        """交付语境缺件仍阻断（既有行为不变），即便同 SPEC 还有引用类路径。"""
        self.make_ready_spec("s1")
        self.write_spec_dir(
            "s1",
            _REFERENCE_ONLY_TASKS + "- [ ] 1.2 写 `core/foo.py`\n")
        self.wm.file_exists_on_branch.return_value = False
        self.assertEqual(self.run_gate(), ["core/foo.py"])

    def test_fenix_prefix_normalize_recheck(self):
        """归一化复检：`.fenix/x` 缺失时以根路径 `x` 复检，命中即放行。"""
        repo = Path(tempfile.mkdtemp())
        try:
            subprocess.run(["git", "init", "-q", repo], check=True)
            subprocess.run(["git", "-C", str(repo), "config",
                            "user.email", "t@t"], check=True)
            subprocess.run(["git", "-C", str(repo), "config",
                            "user.name", "t"], check=True)
            (repo / "core").mkdir()
            (repo / "core" / "agent_runner.py").write_text("# frame\n",
                                                          encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"],
                           check=True)
            branch = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, check=True).stdout.strip()

            real_wm = WorktreeManager(repo, repo, _FakeLogger())
            # 链接 blob 语义：`.fenix/...` 在分支树中无法按树查找
            self.assertFalse(
                real_wm.file_exists_on_branch(branch, ".fenix/core/agent_runner.py"))
            self.assertTrue(
                real_wm.file_exists_on_branch(branch, "core/agent_runner.py"))

            self.make_ready_spec("s1")
            self.write_spec_dir(
                "s1", "- [ ] 1.1 扩展 `.fenix/core/agent_runner.py`\n")
            self.runner.worktree_manager = real_wm
            self.assertEqual(self.run_gate(branch=branch), [])
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_fenix_prefix_normalize_recheck_real_branch_fixture(self):
        """真实分支夹具回归（复现热修 4461231 行为）：interaction-contract 分支。"""
        probe = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "cat-file", "-e",
             f"{INTERACTION_CONTRACT_BRANCH}:core/agent_runner.py"],
            capture_output=True)
        if probe.returncode != 0:
            self.skipTest(f"回归夹具分支不存在：{INTERACTION_CONTRACT_BRANCH}")

        real_wm = WorktreeManager(REPO_ROOT, REPO_ROOT, _FakeLogger())
        self.assertFalse(
            real_wm.file_exists_on_branch(INTERACTION_CONTRACT_BRANCH,
                                          ".fenix/core/agent_runner.py"))
        self.assertTrue(
            real_wm.file_exists_on_branch(INTERACTION_CONTRACT_BRANCH,
                                          "core/agent_runner.py"))

        self.make_ready_spec("s1")
        self.write_spec_dir(
            "s1", "- [ ] 1.1 扩展 `.fenix/core/agent_runner.py`\n")
        self.runner.worktree_manager = real_wm
        self.assertEqual(
            self.run_gate(branch=INTERACTION_CONTRACT_BRANCH), [])


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
        prompt = self.runner._prompt_builder._build_prompt("s1", "implementer")
        self.assertNotIn("Previous run error", prompt)

    def test_deliverable_guard_error_injected(self):
        self.sm.add_spec("s1", {"priority": 5})
        self.sm.update_spec("s1", {
            "error": "交付物守卫：缺件 [core/foo.py] — 不合并不推进，重派实现补齐（第 1 次）",
        })
        prompt = self.runner._prompt_builder._build_prompt("s1", "implementer")
        self.assertIn("Previous run error", prompt)
        self.assertIn("交付物守卫：缺件 [core/foo.py]", prompt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
