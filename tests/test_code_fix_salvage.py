"""test_code_fix_salvage.py — 收尾 salvage commit 兜底测试

add-codefix-commit-first-contract 3.1-3.4：
- 3.1 搁浅批（fixed 声明 + 未提交修改 + 零提交）→ salvage commit 触发、
  message 可追溯（``orchestrator-salvage: batch <batch_no> run <run_id>``）、
  合回核销成功。
- 3.2 真零改动批（fixed 声明 + 零提交 + 工作区干净）→ 维持 ``no_effective_fix``
  拒合回、无 salvage 提交、链继续推进。
- 3.3 salvage 后分支 diff 与原工作区改动一致（gitignored 噪音不卷入）。
- 3.4 ``agents/code-fix.md`` 「先 commit 再验证」契约段三要点机械可检出。

MUST NOT 真跑 agent——全部用 fake runner / 临时目录。
"""

import json
import subprocess
import unittest
from pathlib import Path

from test_code_fix import (
    _CFG_ON,
    _item,
    _make_project_root,
    _write_items,
    _write_verify_yaml,
)
from test_code_fix import _FakeRunner, _FakeWM


class _RecordingLogger:
    """捕获日志的 fake logger（编排器 _log 形如 logger.warning(tag, msg)）。"""

    def __init__(self):
        self.records = []

    def warning(self, tag, msg):
        self.records.append(("warning", tag, msg))

    def error(self, tag, msg):
        self.records.append(("error", tag, msg))

    def info(self, tag, msg):
        self.records.append(("info", tag, msg))


class _StrandedRunner(_FakeRunner):
    """搁浅批模拟（09-25 实证机理）：fix-out 产物行写 fixed、改动落盘，
    但 agent **从不 commit**——把验证丢后台后回合结束。"""

    def __init__(self, project_root):
        super().__init__(project_root, fix_statuses=[["fixed"]])
        self.out_run_ids = []

    def run_code_fix(self, worktree_root, items, run_id=None, failure_summary=""):
        self._run_no += 1
        rid = run_id or f"code-fix-stranded-{self._run_no}"
        self.out_run_ids.append(rid)
        self.fix_calls.append((str(worktree_root), len(items), failure_summary))
        wt = Path(worktree_root)
        out = wt / ".fenix" / "code-review" / f"fix-out-{rid}.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as fh:
            for it in items:
                fh.write(json.dumps(
                    {"item_id": it["item_id"], "status": "fixed",
                     "file": it.get("file", "")}, ensure_ascii=False) + "\n")
        self.touch(wt)
        import types as _t
        return _t.SimpleNamespace(run_id=rid, success=True, fixed=len(items),
                                  skipped=0, error="", output="done")

    def touch(self, wt):  # pragma: no cover — 由子类覆写
        pass


class _StrandedWithChangesRunner(_StrandedRunner):
    """留未提交改动：改一个已跟踪文件 + 新增一个源码文件 + 一个 gitignored 噪音。"""

    def touch(self, wt):
        (wt / "README.md").write_text("init\nfixed\n", encoding="utf-8")
        (wt / "salvaged_fix.py").write_text("# fixed\n", encoding="utf-8")
        (wt / "debug.log").write_text("noise\n", encoding="utf-8")


class _StrandedNoChangesRunner(_StrandedRunner):
    """真零改动：只写产物行，不动任何文件（声明与事实不符）。"""

    def touch(self, wt):
        pass


class _SalvageWM(_FakeWM):
    """_FakeWM 变体：worktree 带跟踪入库的 .gitignore（对齐真实 worktree），
    merge_back 时抓取分支 tip subject 与相对建树点的 diff 清单供断言。"""

    def __init__(self):
        super().__init__(create_result="git")
        self.merge_subjects = []    # merge_back 时刻 HEAD 提交 subject
        self.merge_diff_names = []  # merge_back 时刻 分支 diff 文件名
        self._root_sha = ""

    def create(self, spec_name, agent_type="implementer"):
        repo = super().create(spec_name, agent_type)
        if repo is not None:
            git = ["git", "-C", str(repo)]
            # 真实 worktree 的 .gitignore 是跟踪文件；.fenix/（运行时产物）与
            # *.log（噪音）被忽略
            (repo / ".gitignore").write_text(".fenix/\n*.log\n", encoding="utf-8")
            subprocess.run(git + ["add", "-A"], check=True, capture_output=True)
            subprocess.run(
                git + ["-c", "user.email=t@t", "-c", "user.name=t",
                       "commit", "-q", "-m", "gitignore"],
                check=True, capture_output=True)
            self._root_sha = subprocess.run(
                git + ["rev-parse", "HEAD"],
                check=True, capture_output=True, text=True).stdout.strip()
        return repo

    def merge_back(self, wt_path):
        git = ["git", "-C", str(wt_path)]
        self.merge_subjects.append(subprocess.run(
            git + ["log", "-1", "--format=%s"],
            capture_output=True, text=True).stdout.strip())
        self.merge_diff_names.append(subprocess.run(
            git + ["diff", "--name-only", self._root_sha, "HEAD"],
            capture_output=True, text=True).stdout.split())
        return super().merge_back(wt_path)


def _checkpoint_with_capture(proot, runner, logger):
    """跑一次 checkpoint，同时捕获 write_progress 的 current 序列。"""
    import core.code_fix as mod

    currents = []
    orig = mod.write_progress

    def _rec(root, **fields):
        currents.append(fields.get("current", ""))
        return orig(root, **fields)

    mod.write_progress = _rec
    try:
        from core.code_fix import CodeFixOrchestrator

        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=logger)
        orch.checkpoint()
    finally:
        mod.write_progress = orig
    return currents


class TestSalvageStrandedBatch(unittest.TestCase):
    """3.1 搁浅批：salvage 触发、message 可追溯、合回核销成功。"""

    def test_stranded_batch_salvaged_and_merged(self):
        from core.code_fix import read_progress
        from core.code_review import read_items

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a"), "b": _item("b")})
        _write_verify_yaml(proot)
        logger = _RecordingLogger()
        runner = _StrandedWithChangesRunner(proot)
        wm = _SalvageWM()
        runner.worktree_manager = wm

        currents = _checkpoint_with_capture(proot, runner, logger)

        rid = runner.out_run_ids[0]
        # salvage 触发 → 正常合回
        self.assertEqual(len(wm.merge_calls), 1, "搁浅批 salvage 后 MUST 合回")
        self.assertEqual(
            wm.merge_subjects,
            [f"orchestrator-salvage: batch 1 run {rid}"],
            "salvage commit message MUST 含批号与 run_id（可追溯）")
        # 合回核销成功：fixed 条目全部 resolved，进度 done 增加
        items = read_items(proot)
        self.assertEqual(items["a"]["status"], "resolved")
        self.assertEqual(items["b"]["status"], "resolved")
        prog = read_progress(proot)
        self.assertEqual(prog["done"], 2)
        self.assertEqual(prog["chain_skipped"], [])
        # 留痕：warning 日志 + 进度 current 都有 salvage 痕迹
        self.assertTrue(
            any(level == "warning" and "salvage" in msg
                for level, _, msg in logger.records),
            "salvage 事件 MUST 写 warning 日志留痕")
        self.assertTrue(
            any("salvage" in c for c in currents),
            "salvage 事件 MUST 写进度 current 留痕")


class TestTrueZeroChangeRejectsMerge(unittest.TestCase):
    """3.2 真零改动批：维持拒合回、无 salvage 提交、链继续。"""

    def test_zero_change_batch_still_rejected(self):
        from core.code_fix import load_failed_batches, read_progress
        from core.code_review import read_items

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a"), "b": _item("b")})
        _write_verify_yaml(proot)
        logger = _RecordingLogger()
        runner = _StrandedNoChangesRunner(proot)
        wm = _SalvageWM()
        runner.worktree_manager = wm

        currents = _checkpoint_with_capture(proot, runner, logger)

        # 无合回、无 salvage 提交（merge 未发生；日志无 salvage 痕迹）
        self.assertEqual(wm.merge_calls, [], "真零改动 MUST NOT 合回")
        self.assertEqual(wm.merge_subjects, [], "真零改动 MUST NOT salvage 提交")
        self.assertFalse(
            any("salvage" in msg for _, _, msg in logger.records),
            "真零改动 MUST NOT 触发 salvage")
        self.assertFalse(any("salvage" in c for c in currents))
        # 维持既有 no_effective_fix 拒合回语义：条目保持 open、入 chain_skipped
        # （链继续）、不入失败档案
        items = read_items(proot)
        self.assertEqual(items["a"]["status"], "open")
        self.assertEqual(items["b"]["status"], "open")
        prog = read_progress(proot)
        self.assertEqual(prog["chain_skipped"], ["a", "b"])
        self.assertEqual(load_failed_batches(proot), [])


class TestSalvageDiffFidelity(unittest.TestCase):
    """3.3 salvage 后分支 diff 与原工作区改动一致（无 gitignored 噪音卷入）。"""

    def test_salvage_diff_matches_working_tree_without_noise(self):
        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        runner = _StrandedWithChangesRunner(proot)
        wm = _SalvageWM()
        runner.worktree_manager = wm

        _checkpoint_with_capture(proot, runner, _RecordingLogger())

        self.assertEqual(len(wm.merge_diff_names), 1)
        self.assertEqual(
            sorted(wm.merge_diff_names[0]),
            ["README.md", "salvaged_fix.py"],
            "salvage 分支 diff MUST 与工作区源码改动一致；gitignored 噪音"
            "（debug.log / .fenix/ 运行时产物）MUST NOT 被卷入")


class TestPromptContractSection(unittest.TestCase):
    """3.4 契约段存在性断言：三要点机械可检出。"""

    @classmethod
    def setUpClass(cls):
        cls.template = (
            Path(__file__).resolve().parent.parent
            / "agents" / "code-fix.md"
        ).read_text(encoding="utf-8")

    def test_commit_first_contract_section_detectable(self):
        t = self.template
        self.assertIn("先 commit 再验证", t, "MUST 存在「先 commit 再验证」契约段")
        for point in ("逐条修复即 commit", "验证不阻塞 commit", "收尾工作区干净"):
            self.assertIn(point, t, f"契约段 MUST 含要点：{point}")
        # 违约后果可检出（salvage 兜底 / 拒合回重做）
        self.assertIn("orchestrator-salvage", t)
        self.assertIn("no_effective_fix", t)

    def test_conflicting_wording_removed(self):
        """与「边修复边提交」互斥的旧口径 MUST NOT 残留（task 1.2）。"""
        t = self.template
        self.assertNotIn("MUST NOT 多次提交", t)
        self.assertNotIn("验证（一次，提交前）", t)
        self.assertNotIn("全部条目处置并验证后，单次提交", t)


if __name__ == "__main__":
    unittest.main()
