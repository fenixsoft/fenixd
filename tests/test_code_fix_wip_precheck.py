"""test_code_fix_wip_precheck.py — code-fix 选批前 WIP 重叠预检回归
（evo-add-codefix-batch-wip-precheck 2.1）

覆盖三场景：
- 主树脏 tracked 文件与候选批条目 file 重叠 → 整批推迟（progress 写
  wip_overlap_at_select + 交集文案；不投递、不置单飞、台账条目保持 open）；
- 无重叠 → 选批投递行为与现状一致（同步链正常跑完核销）；
- 交集仅含 dist 类产物路径（与 merge-time 闸门同口径豁免）→ 不误伤、照常
  投递；产物配置未裁决时同路径仍按语义重叠推迟（同口径对照，非预检私设）。

MUST NOT 真跑 agent——复用 tests/test_code_fix.py 的 fake runner / 临时目录
脚手架。
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from test_code_fix import (  # noqa: E402
    _CFG_ON,
    _FakeRunner,
    _RealCfgRunner,
    _make_project_root,
    _write_items,
    _write_verify_yaml,
)

_HISTORY_TMP = _TESTS_DIR.parent / ".history" / "tmp"
_HISTORY_TMP.mkdir(parents=True, exist_ok=True)


def _mkdtemp(prefix: str) -> str:
    return tempfile.mkdtemp(prefix=prefix, dir=str(_HISTORY_TMP))


def _item(item_id, status="open", **extra):
    rec = {"item_id": item_id, "status": status, "file": f"{item_id}/{item_id}.py",
           "line": 1, "severity": "major", "category": "correctness",
           "title": f"title {item_id}", "description": f"desc {item_id}",
           "suggestion": f"sug {item_id}", "fingerprint": f"fp-{item_id}",
           "first_seen_at": "2026-01-01T00:00:00Z"}
    rec.update(extra)
    return rec


def _git(proot, args):
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t"] + args,
        cwd=proot, check=True, capture_output=True)


def _make_git_project_root() -> Path:
    """带初始提交的临时项目根（预检需真实 ``git status`` 可执行）。"""
    proot = Path(_mkdtemp("cfix-wip-"))
    (proot / ".fenix" / "code-review").mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=proot, check=True, capture_output=True)
    (proot / "README.md").write_text("init", encoding="utf-8")
    _git(proot, ["add", "-A"])
    _git(proot, ["commit", "-q", "-m", "init"])
    return proot


def _track_and_dirty(proot: Path, rel: str):
    """让 rel 成为 tracked 且工作区已修改的文件（porcelain ' M'，主树 WIP）。"""
    p = Path(proot) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("committed\n", encoding="utf-8")
    _git(proot, ["add", rel])
    _git(proot, ["commit", "-q", "-m", f"track {rel}"])
    p.write_text("wip-uncommitted\n", encoding="utf-8")


_ARTIFACT_CFG = {
    "admin": {"code_review_fix": {"enabled": True, "batch_size": 20}},
    "worktree": {"has_build_artifacts": True, "build_artifact_paths": ["dist/"]},
}


class TestWipOverlapDefersBatch(unittest.TestCase):
    """场景一：主树脏文件与候选批重叠 → 整批推迟（1.1/1.2）。"""

    def test_overlap_defers_whole_batch(self):
        from core.code_fix import CodeFixOrchestrator, read_progress
        from core.code_review import read_items

        proot = _make_git_project_root()
        _track_and_dirty(proot, "core/a.py")
        _write_items(proot, {"a": _item("a", file="core/a.py")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot)
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=None)
        res = orch.checkpoint()
        self.assertEqual(
            res, {"triggered": False, "reason": "wip_overlap_at_select"})
        # 不投递：无 agent run、无建树、不置单飞（不耗实现预算）
        self.assertEqual(runner.fix_calls, [])
        self.assertEqual(runner.worktree_manager.create_calls, [])
        self.assertFalse(orch._in_flight, "MUST NOT 置单飞")
        # 无条件写进度（无 live 链首查也写——推迟可观测，1.2）
        prog = read_progress(proot)
        self.assertFalse(prog["running"])
        self.assertEqual(prog["phase"], "blocked")
        self.assertEqual(prog["reason"], "wip_overlap_at_select")
        self.assertIn("core/a.py", prog["current"], "current 携带交集文件文案")
        # 台账条目保持 open 待下轮（重查后投递）
        items = read_items(proot)
        self.assertEqual(items["a"]["status"], "open")

    def test_partial_overlap_defers_whole_batch(self):
        """批内仅一条重叠 → 整批推迟，文案只列重叠文件。"""
        from core.code_fix import CodeFixOrchestrator, read_progress

        proot = _make_git_project_root()
        _track_and_dirty(proot, "core/b.py")
        _write_items(proot, {
            "a": _item("a"),
            "b": _item("b", file="core/b.py"),
        })
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot)
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=None)
        res = orch.checkpoint()
        self.assertEqual(
            res, {"triggered": False, "reason": "wip_overlap_at_select"})
        self.assertEqual(runner.fix_calls, [], "整批推迟：无重叠条目也不投递")
        prog = read_progress(proot)
        self.assertEqual(prog["reason"], "wip_overlap_at_select")
        self.assertIn("core/b.py", prog["current"])
        self.assertNotIn("core/a.py", prog["current"],
                         "交集文案只列重叠文件，不含无关批条目")


class TestNoOverlapDispatches(unittest.TestCase):
    """场景二：无重叠 → 选批投递行为与现状一致。"""

    def test_dirty_file_outside_batch_dispatches(self):
        """主树有 WIP 但与批无交集 → 正常同步链投递并核销。"""
        from core.code_fix import CodeFixOrchestrator
        from core.code_review import read_items

        proot = _make_git_project_root()
        _track_and_dirty(proot, "docs/notes.md")
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot)
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=None)
        res = orch.checkpoint()
        self.assertEqual(res, {"triggered": True, "reason": "dispatched"})
        self.assertEqual(len(runner.fix_calls), 1)
        self.assertEqual(len(runner.worktree_manager.merge_calls), 1)
        self.assertEqual(read_items(proot)["a"]["status"], "resolved")

    def test_non_git_root_fails_open_to_dispatch(self):
        """非 git 根（git status 失败）按「无重叠」fail-open，不阻塞选批。"""
        from core.code_fix import CodeFixOrchestrator
        from core.code_review import read_items

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot)
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=None)
        res = orch.checkpoint()
        self.assertEqual(res, {"triggered": True, "reason": "dispatched"})
        self.assertEqual(read_items(proot)["a"]["status"], "resolved")


class TestArtifactOverlapExempt(unittest.TestCase):
    """场景三：交集仅含 dist 类产物路径 → 不误伤（与 merge-time 同口径）。"""

    def _make_case(self):
        proot = _make_git_project_root()
        _track_and_dirty(proot, "dist/app.js")
        _write_items(proot, {"a": _item("a", file="dist/app.js")})
        _write_verify_yaml(proot)
        return proot

    def test_artifact_only_overlap_dispatches(self):
        """已裁决产物配置（has_build_artifacts=true + dist/ 前缀）→ 豁免。"""
        from core.code_fix import CodeFixOrchestrator
        from core.code_review import read_items

        proot = self._make_case()
        runner = _FakeRunner(proot)
        orch = CodeFixOrchestrator(runner, proot, config=dict(_ARTIFACT_CFG),
                                   logger=None)
        res = orch.checkpoint()
        self.assertEqual(res, {"triggered": True, "reason": "dispatched"})
        self.assertEqual(len(runner.fix_calls), 1)
        self.assertEqual(read_items(proot)["a"]["status"], "resolved")

    def test_unresolved_config_treats_as_semantic_overlap(self):
        """产物配置未裁决（空 patterns 判定恒假）→ 按语义重叠推迟。

        与 merge-time 闸门同语义：未裁决时 dist 脏文件同样算语义重叠，预检
        不私设豁免口径（同口径 = 同配置源，先例 lifecycle.py:127）。
        """
        from core.code_fix import CodeFixOrchestrator, read_progress

        proot = self._make_case()
        runner = _FakeRunner(proot)
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=None)
        res = orch.checkpoint()
        self.assertEqual(
            res, {"triggered": False, "reason": "wip_overlap_at_select"})
        self.assertEqual(read_progress(proot)["reason"], "wip_overlap_at_select")

    def test_daemon_form_config_artifact_exempt(self):
        """daemon 装配形态（config=None → runner 根 config）豁免同样生效。

        回归锁：预检产物配置与 code_review_fix 开关 MUST 同源解析
        （_get_root_config 单点），否则生产路径上豁免静默退化。
        """
        from core.code_fix import CodeFixOrchestrator
        from core.code_review import read_items

        proot = self._make_case()
        runner = _RealCfgRunner(proot)
        runner.config = dict(_ARTIFACT_CFG)
        orch = CodeFixOrchestrator(runner, proot, config=None, logger=None)
        res = orch.checkpoint()
        self.assertEqual(res, {"triggered": True, "reason": "dispatched"})
        self.assertEqual(read_items(proot)["a"]["status"], "resolved")


if __name__ == "__main__":
    unittest.main()
