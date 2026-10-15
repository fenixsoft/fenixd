"""test_code_fix_api_timeout_salvage.py — api_timeout 签名与失败现场 salvage 链路测试

evo-code-fix-api-timeout-salvage 3.1/3.2：
- 3.1 签名判别：末次 result 事件 terminal_reason=="api_error" 与 synthetic
  "Request timed out" 两形态命中；确定性失败 / 空 result 不误标；run_code_fix
  失败信封透出结构化签名（api_timeout / exit_code / stderr 摘要）。
- 3.2 salvage 链路：失败分支 salvage commit 落批分支 → cleanup(success=False)
  登记 recovery legacy → mark_legacy_reusable 置 reuse → 下一批 wm.create 经
  既有 _take_reusable_worktree 通路认领继承 salvaged 分支；认领不可用
  fail-open 全新建树；工作区干净 / 非 api_timeout 失败不做 salvage（2.3）。

MUST NOT 真跑 agent——全部用 fake runner / 临时目录；认领链路用真实
WorktreeManager（对齐 test_code_fix.py 的真实 WM 用法）。
"""

import shutil
import subprocess
import time
import types as _t
import unittest
from pathlib import Path

from test_code_fix import (
    _CFG_ON,
    _FakeRunner,
    _FakeWM,
    _item,
    _make_git_repo,
    _make_project_root,
    _make_runner,
    _mkdtemp,
    _write_items,
    _write_verify_yaml,
)

from core.agent_runner.runner import is_api_timeout_signature
from core.worktree_manager import WorktreeManager


class _RecordingLogger:
    """捕获日志的 fake logger（编排器/WM _log 形如 logger.warning(tag, msg)）。"""

    def __init__(self):
        self.records = []

    def debug(self, tag, msg, extra=None):
        self.records.append(("debug", tag, msg))

    def info(self, tag, msg, extra=None):
        self.records.append(("info", tag, msg))

    def warning(self, tag, msg, extra=None):
        self.records.append(("warning", tag, msg))

    def error(self, tag, msg, extra=None):
        self.records.append(("error", tag, msg))


def _git_init_repo(proot: Path) -> None:
    """把临时项目根变成可用 git 仓（真实 WorktreeManager 建树/合回必需）。

    .fenix/（运行时产物）与 *.log 预先 gitignore，进度/台账写盘不脏主树
    （merge-back WIP 闸门与选批预检不受干扰）。
    """
    (proot / ".gitignore").write_text(".fenix/\n*.log\n", encoding="utf-8")
    (proot / "README.md").write_text("init\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=proot, check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(proot), "add", "-A"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(proot), "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "-m", "init"],
        check=True, capture_output=True,
    )


def _git_branch(worktree) -> str:
    out = subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def _git_log_subjects(repo) -> list:
    """全可达提交 subject（含未合回分支：--all，salvage commit 无处遁形）。"""
    out = subprocess.run(
        ["git", "-C", str(repo), "log", "--all", "--format=%s"],
        capture_output=True, text=True,
    )
    return [s for s in out.stdout.splitlines() if s.strip()]


def _sleep_past_timestamp() -> None:
    """分支名含秒级时间戳（create 端硬编码），隔秒防同名撞分支。"""
    time.sleep(1.1)


class _ApiTimeoutFailRunner(_FakeRunner):
    """首轮 run_code_fix 以 api_timeout 签名失败的信封（后续批走基类成功路径）。

    ``dirty=True`` 时在工作区留未提交改动（模拟 316 turns 后死于单轮超时的
    失败现场）；``dirty=False`` 模拟工作区干净终局（Requirement 4）。
    """

    def __init__(self, project_root, dirty=True):
        super().__init__(project_root, fix_statuses=[["fixed"]])
        self._dirty = dirty
        self._call_no = 0

    def run_code_fix(self, worktree_root, items, run_id=None, failure_summary=""):
        self._call_no += 1
        if self._call_no > 1:
            return super().run_code_fix(
                worktree_root, items, run_id=run_id, failure_summary=failure_summary
            )
        self.fix_calls.append((str(worktree_root), len(items), failure_summary))
        if self._dirty:
            wt = Path(worktree_root)
            (wt / "salvaged_fix.py").write_text(
                "# salvaged from api timeout\n", encoding="utf-8")
        return _t.SimpleNamespace(
            run_id=run_id or "code-fix-apitimeout-1",
            success=False, fixed=0, skipped=0,
            error=(
                "claude CLI failed: Exit code: 1 "
                "[api_timeout=True exit_code=1 stderr_tail: Request timed out]"
            ),
            output="", api_timeout=True, exit_code=1,
            stderr_summary="Request timed out")


class _DeterministicFailRunner(_FakeRunner):
    """非 api_timeout（确定性）失败 + 工作区脏：2.3 现状行为保形用。"""

    def __init__(self, project_root):
        super().__init__(project_root, fix_statuses=[["fixed"]])

    def run_code_fix(self, worktree_root, items, run_id=None, failure_summary=""):
        self.fix_calls.append((str(worktree_root), len(items), failure_summary))
        wt = Path(worktree_root)
        (wt / "wip_fix.py").write_text("# deterministic failure wip\n", encoding="utf-8")
        return _t.SimpleNamespace(
            run_id=run_id or "code-fix-detfail-1",
            success=False, fixed=0, skipped=0,
            error=(
                "claude CLI failed: Exit code: 1 "
                "[api_timeout=False exit_code=1 stderr_tail: TypeError: boom]"
            ),
            output="", api_timeout=False, exit_code=1,
            stderr_summary="TypeError: boom")


# ── 3.1 签名判别 ────────────────────────────────────────────────────────


class TestApiTimeoutSignature(unittest.TestCase):
    """3.1：terminal_reason=="api_error" 与 synthetic 超时文本两形态命中。"""

    def test_terminal_reason_api_error_hits(self):
        self.assertTrue(is_api_timeout_signature({
            "subtype": "success", "is_error": True,
            "terminal_reason": "api_error",
            "result": "API Error: 500 overloaded",
        }))

    def test_synthetic_timeout_text_hits(self):
        # 现场签名（code-fix-1790453264）：CLI 合成超时文本 + Exit 1
        self.assertTrue(is_api_timeout_signature({
            "subtype": "error_during_execution", "is_error": True,
            "num_turns": 316,
            "result": "claude CLI: Request timed out after 1549.9s",
        }))

    def test_timeout_text_outside_result_field_not_hit(self):
        # 只认 result 文本与 terminal_reason 两个位置（判别单源，防误标扩散）
        self.assertFalse(is_api_timeout_signature({
            "stderr": "Request timed out", "result": "done",
        }))

    def test_deterministic_failure_not_mislabeled(self):
        self.assertFalse(is_api_timeout_signature({
            "subtype": "error_during_execution", "is_error": True,
            "result": "TypeError: unsupported operand type(s)",
        }))
        self.assertFalse(is_api_timeout_signature({
            "terminal_reason": "turn_limit", "result": "max turns reached",
        }))
        self.assertFalse(is_api_timeout_signature({
            "subtype": "success", "is_error": False, "result": "all fixed",
        }))

    def test_empty_result_not_mislabeled(self):
        self.assertFalse(is_api_timeout_signature(None))
        self.assertFalse(is_api_timeout_signature({}))


class TestRunCodeFixSignatureEnvelope(unittest.TestCase):
    """1.2：run_code_fix 失败信封透出结构化签名，替代仅 str(e) 压扁。"""

    @staticmethod
    def _runner_with(proot, run_claude):
        runner = _make_runner(proot)
        runner._get_agent_model_assignment = lambda t: None
        runner._get_admin_model = lambda: "admin-model"
        runner._run_agent = run_claude
        return runner

    def test_api_timeout_failure_carries_structured_signature(self):
        from core.agent_runner.maintenance_runs import run_code_fix

        def fake_claude(prompt, cwd, run_id, model, env, **kw):
            e = RuntimeError("claude CLI failed: Exit code: 1")
            e.api_timeout = True
            e.exit_code = 1
            e.stderr_lines = [
                "[claude-code:infra] retrying request",
                "Request timed out after 1549.9s",
            ]
            raise e

        result = run_code_fix(
            self._runner_with(_make_project_root(), fake_claude),
            _make_project_root(), [_item("a")])
        self.assertFalse(result.success)
        self.assertTrue(result.api_timeout, "api_timeout 布尔标记 MUST 上信封")
        self.assertEqual(result.exit_code, 1)
        self.assertIn("Request timed out", result.stderr_summary)
        # 失败记录（error 文本，随编排器日志落痕）携带结构化签名
        self.assertIn("api_timeout=True", result.error)
        self.assertIn("exit_code=1", result.error)

    def test_deterministic_failure_not_flagged(self):
        from core.agent_runner.maintenance_runs import run_code_fix

        def fake_claude(prompt, cwd, run_id, model, env, **kw):
            e = RuntimeError("claude CLI failed: Exit code: 1")
            e.exit_code = 1
            e.stderr_lines = ["TypeError: boom"]
            raise e

        result = run_code_fix(
            self._runner_with(_make_project_root(), fake_claude),
            _make_project_root(), [_item("a")])
        self.assertFalse(result.success)
        self.assertFalse(result.api_timeout, "确定性失败 MUST NOT 误标 api_timeout")
        self.assertEqual(result.exit_code, 1)
        self.assertIn("api_timeout=False", result.error)

    def test_plain_exception_keeps_error_verbatim(self):
        from core.agent_runner.maintenance_runs import run_code_fix

        def fake_claude(prompt, cwd, run_id, model, env, **kw):
            raise RuntimeError("boom without signals")

        result = run_code_fix(
            self._runner_with(_make_project_root(), fake_claude),
            _make_project_root(), [_item("a")])
        self.assertFalse(result.success)
        self.assertFalse(result.api_timeout)
        self.assertIsNone(result.exit_code)
        self.assertEqual(result.error, "boom without signals",
                         "无信号异常 MUST NOT 添噪（error 保持原文）")

    def test_artifact_gate_failure_not_flagged(self):
        """run_ok 被产物硬门置 False 的路径（except 未执行）不误标、不炸。"""
        from core.agent_runner.maintenance_runs import run_code_fix

        def fake_claude(prompt, cwd, run_id, model, env, **kw):
            return ("done", 1, "sid", {}, {"rounds": 1, "stalls": 0, "max": 0.0})

        result = run_code_fix(
            self._runner_with(_make_project_root(), fake_claude),
            _make_project_root(), [_item("a")])  # out 缺失 → 硬门失败
        self.assertFalse(result.success)
        self.assertFalse(result.api_timeout)
        self.assertIsNone(result.exit_code)


# ── 3.2 salvage 链路（真实 WorktreeManager）────────────────────────────


class TestSalvageLegacyClaimPath(unittest.TestCase):
    """3.2 / 2.2：salvage commit 落批分支 → legacy 登记 + reuse → 认领继承 / fail-open。"""

    def _wm_with_salvaged_legacy(self):
        """建真实 WM + code-fix worktree，salvage 提交 WIP 后按失败清理登记 legacy。

        逐字复刻生产链路（code_fix._run_batch_created 失败分支）：agent 留 WIP
        → ``_salvage_commit`` 提交批分支 → ``cleanup(success=False)`` 登记
        recovery legacy（非 verify- 前缀分支既有语义）。
        """
        from core.code_fix import _salvage_commit

        repo = _make_git_repo()
        base = Path(_mkdtemp("apitimeout-claim-"))
        wm = WorktreeManager(base, repo, _RecordingLogger())
        wt = wm.create(spec_name="code-review-fix", agent_type="code-fix")
        self.assertIsNotNone(wt)
        wt = Path(wt)
        # agent WIP：改 tracked 文件 + 新增源码文件
        (wt / "README.md").write_text("init\nwip\n", encoding="utf-8")
        (wt / "wip_fix.py").write_text("# fix\n", encoding="utf-8")
        self.assertTrue(
            _salvage_commit(wt, "api-timeout-salvage: batch 1 run r1"),
            "salvage 提交 MUST 成功（工作区脏）")
        branch = _git_branch(wt)
        wm.cleanup(wt, success=False)
        return wm, repo, wt, branch

    def test_salvage_commit_lands_on_batch_branch_and_reuse_marked(self):
        wm, repo, wt, branch = self._wm_with_salvaged_legacy()
        # salvage commit 落在批分支（而非悬空 stash/快照）
        out = subprocess.run(
            ["git", "-C", str(wt), "log", "-1", "--format=%s"],
            capture_output=True, text=True, check=True)
        self.assertEqual(out.stdout.strip(), "api-timeout-salvage: batch 1 run r1")
        # cleanup(success=False) 登记 recovery legacy（宽限期豁免陈旧清扫）
        rec = wm.get_legacy("code-review-fix")
        self.assertIsNotNone(rec, "失败清理 MUST 登记 recovery legacy 保全现场")
        self.assertEqual(rec["branch"], branch)
        self.assertEqual(rec["path"], str(wt), "worktree 模式：目录随 legacy 保全")
        # register_legacy 自身不置 reuse；编排器补 mark_legacy_reusable
        self.assertFalse(rec.get("reuse"))
        self.assertTrue(wm.mark_legacy_reusable("code-review-fix"))
        self.assertTrue(wm.get_legacy("code-review-fix")["reuse"])

    def test_next_batch_create_claims_salvaged_branch(self):
        wm, repo, wt, branch = self._wm_with_salvaged_legacy()
        self.assertTrue(wm.mark_legacy_reusable("code-review-fix"))
        _sleep_past_timestamp()
        wt2 = wm.create(spec_name="code-review-fix", agent_type="code-fix")
        self.assertIsNotNone(wt2)
        self.assertEqual(
            Path(wt2), Path(wt),
            "下一批 create MUST 经 _take_reusable_worktree 认领 salvaged 载体")
        self.assertEqual(_git_branch(wt2), branch, "认领 MUST 继承批分支")
        self.assertTrue(
            (Path(wt2) / "wip_fix.py").exists(),
            "salvaged 提交 MUST 对重试批可见")
        self.assertIsNone(wm.get_legacy("code-review-fix"), "认领即摘出遗产")
        wm.cleanup(wt2, success=True)

    def test_claim_unavailable_fails_open_to_fresh_worktree(self):
        wm, repo, wt, branch = self._wm_with_salvaged_legacy()
        self.assertTrue(wm.mark_legacy_reusable("code-review-fix"))
        # 载体失效（陈旧清扫 / 外力删除）：认领 MUST fail-open 全新建树
        shutil.rmtree(wt, ignore_errors=True)
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "prune"],
            capture_output=True, timeout=10)
        _sleep_past_timestamp()
        wt2 = wm.create(spec_name="code-review-fix", agent_type="code-fix")
        self.assertIsNotNone(wt2, "认领不可用 MUST NOT 阻断建树（车道死锁即事故）")
        self.assertNotEqual(Path(wt2), Path(wt))
        self.assertNotEqual(_git_branch(wt2), branch, "fail-open = 全新建树（新分支）")
        self.assertIsNone(wm.get_legacy("code-review-fix"), "无效 legacy 认领时清除")
        wm.cleanup(wt2, success=True)


class TestApiTimeoutSalvageChain(unittest.TestCase):
    """3.2 编排链路：失败批 salvage → 下一批认领继承 → salvaged 工作随重试批合回。"""

    def test_full_chain_salvage_reuse_and_next_batch_claim(self):
        from core.code_fix import CodeFixOrchestrator
        from core.code_review import read_items
        from core.worktree_manager import WorktreeManager

        proot = _make_project_root()
        _git_init_repo(proot)
        _write_items(proot, {"a": _item("a"), "b": _item("b")})
        _write_verify_yaml(proot)
        logger = _RecordingLogger()
        runner = _ApiTimeoutFailRunner(proot, dirty=True)
        wm = WorktreeManager(Path(_mkdtemp("apitimeout-chain-")), proot, logger)
        runner.worktree_manager = wm

        cfg = {"admin": {"code_review_fix": {"enabled": True, "batch_size": 1}}}
        orch = CodeFixOrchestrator(runner, proot, config=cfg, logger=logger)
        orch.checkpoint()

        # 两次 run：第 1 批 api_timeout 失败、第 2 批成功合回（自驱动链同步推进）
        self.assertEqual(len(runner.fix_calls), 2, "失败批跳批推进，链继续")
        # 认领继承：第 2 批在第 1 批同目录同分支上继续（既有认领通路）
        self.assertEqual(
            runner.fix_calls[0][0], runner.fix_calls[1][0],
            "下一批 create MUST 经认领通路继承 salvaged 载体（同目录）")
        # salvage commit 落批分支，且随重试批合回可达（merge --no-ff 保留历史）
        subjects = _git_log_subjects(proot)
        self.assertTrue(
            any(s.startswith("api-timeout-salvage: batch 1 run ") for s in subjects),
            f"salvage commit MUST 落批分支且随合回可达: {subjects}")
        self.assertTrue(
            (proot / "salvaged_fix.py").exists(),
            "salvaged 工作 MUST 随重试批合回进主树（不再悬空蒸发）")
        # legacy 已被下一批认领摘出（登记 → mark_legacy_reusable → create 认领）
        self.assertIsNone(wm.get_legacy("code-review-fix"))
        # 条目语义不变（跳批推进；salvage 不改条目核销状态）：失败批保持 open
        items = read_items(proot)
        self.assertEqual(items["a"]["status"], "open")
        self.assertEqual(items["b"]["status"], "resolved")
        # 留痕：salvage 事件写日志
        self.assertTrue(
            any("salvage" in msg and "api_timeout" in msg
                for _, _, msg in logger.records),
            "api_timeout salvage MUST 写日志留痕")


# ── 2.3 / 场景 2、4：不命中签名的行为保形 ───────────────────────────────


class TestNonApiTimeoutFailureUnchanged(unittest.TestCase):
    """非 api_timeout 与干净工作区不做 salvage：立即清理 + 跳批推进不变。"""

    def test_api_timeout_clean_worktree_skips_salvage(self):
        """场景 4：api_timeout 但工作区干净 → 跳过 salvage 按现状清理。"""
        from core.code_fix import CodeFixOrchestrator
        from core.worktree_manager import WorktreeManager

        proot = _make_project_root()
        _git_init_repo(proot)
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        logger = _RecordingLogger()
        runner = _ApiTimeoutFailRunner(proot, dirty=False)
        wm = WorktreeManager(Path(_mkdtemp("apitimeout-clean-")), proot, logger)
        runner.worktree_manager = wm

        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=logger)
        orch.checkpoint()

        self.assertFalse(
            any("api-timeout-salvage" in s for s in _git_log_subjects(proot)),
            "工作区干净 MUST NOT salvage 提交")
        self.assertTrue(
            any("工作区干净" in msg for _, _, msg in logger.records),
            "跳过 salvage MUST 留痕")
        # 失败清理照常：recovery legacy 登记（既有语义）但 MUST NOT 置 reuse
        rec = wm.get_legacy("code-review-fix")
        self.assertIsNotNone(rec)
        self.assertFalse(
            rec.get("reuse"), "未 salvage MUST NOT 置 reuse（下批全新建树）")

    def test_deterministic_failure_dirty_worktree_no_salvage(self):
        """场景 2：确定性失败即使工作区脏也不 salvage（立即清理 + 跳批推进）。"""
        from core.code_fix import CodeFixOrchestrator, read_progress

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        logger = _RecordingLogger()
        runner = _DeterministicFailRunner(proot)
        wm = _FakeWM()
        runner.worktree_manager = wm

        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=logger)
        orch.checkpoint()

        # 现状行为保形：立即清理（success=False）+ 条目入 chain_skipped
        self.assertEqual(len(wm.cleanup_calls), 1)
        self.assertEqual(wm.cleanup_calls[0][1], False)
        self.assertEqual(read_progress(proot)["chain_skipped"], ["a"])
        self.assertFalse(
            any("salvage" in msg for _, _, msg in logger.records),
            "非 api_timeout 失败 MUST NOT 触发 salvage")
        # 日志仍带结构化签名（1.2 透出的 error 文本随失败日志落痕）
        self.assertTrue(
            any("api_timeout=False" in msg for level, _, msg in logger.records
                if level == "error"),
            "确定性失败日志 MUST 带结构化签名便于追溯")


if __name__ == "__main__":
    unittest.main()
