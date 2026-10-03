"""evo-add-maintree-interactive-session-attribution 单测（tasks.md 3.1）。

覆盖四块（tasks 1.1/1.2/2.1/2.2 的行为面）：
- 探测三分支：活会话命中（候选②最近提交人启发 / 候选③ transcript 活跃
  信号）、零命中（路径无交/无活跃）、源缺失（身份未配置/目录不存在）——
  零命中与源缺失均 fail-open 回无主现状
- WipOccupantInfo 会话形态：occupant_kind / is_session_attribution /
  describe 文案（标注会话线索，不再自认无主盲区）/ to_dict 结构
- stray_wip 盘点侧降级：会话归因散件默认 info 留痕不派 major；配置
  admin.maintree_session_attribution_action=keep（或非法值守卫）回退现状
- code_fix defer 消费点透传：info=采信（owner_kind=holder、无 run_ids 不
  注册终态回调、不升级）、keep=视同零命中走 orphan 宽限升级（evidence 仍
  透传 describe() 会话线索）

进程内真实 git 仓库夹具；transcript 探测经 HOME 环境变量重定向到临时目录
（探测读 ``$HOME/.claude/projects/<munge>``，不触碰真实会话目录）。
"""

import os
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from core.admin_store import AdminStore, SIGNAL
from core.worktree_manager.types import WipOccupantInfo

# /tmp 可能被外部清扫进程周期性清空（test_code_fix 同款规避）。统一用仓库内
# .history/tmp（gitignored），MUST NOT 改写全局 tempfile.tempdir。
_HISTORY_TMP = Path(__file__).resolve().parent.parent / ".history" / "tmp"
_HISTORY_TMP.mkdir(parents=True, exist_ok=True)


def _mkdtemp(prefix: str) -> str:
    return tempfile.mkdtemp(prefix=prefix, dir=str(_HISTORY_TMP))


def _git(*args, cwd, check=True):
    return subprocess.run(
        ["git", "-c", "user.email=s@s", "-c", "user.name=s", *args],
        cwd=str(cwd), check=check, capture_output=True, text=True,
    )


def _git_as_configured(*args, cwd, check=True):
    """git 调用（不注入 -c 身份）：提交读取仓库配置身份（候选②现场用）。"""
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd), check=check, capture_output=True, text=True,
    )


class _WmProbe:
    """WorktreeManager 探针壳：识别/盘点所需 mixin（真实实现，非替身）。

    test_mergeback_wip_coordination._IdentifyProbe /
    test_maintree_stray_wip_sweep._WmProbe 同款装配。
    """

    from core.worktree_manager.mergeback import G4MergebackMixin as _G4
    from core.worktree_manager.queries import G8QueryMixin as _G8
    from core.worktree_manager.stash_guard import G6StashGuardMixin as _G6

    class Inner(_G4, _G6, _G8):
        def __init__(self, root):
            self.project_root = Path(root)
            self._main_tree_lock = threading.Lock()

    def __init__(self, root):
        self.impl = self.Inner(root)

    def __getattr__(self, name):
        return getattr(self.impl, name)


def _make_session_repo(with_local_identity=True):
    """主树仓：候选②「活交互会话直改主树」现场。

    - init 提交（作者 s <s@s>，经 -c 逐命令注入、不落仓库配置）建 a/b.tsx；
    - ``with_local_identity`` 时写入仓库级配置身份 t <t@t>，并做一次近窗
      提交（作者 t，触碰 a.tsx）——与配置身份一致 + 时间窗内 + 路径交；
    - 主树 a.tsx 未提交直改（散件 WIP，与近窗提交触碰集相交）；
    - b.tsx 全场不在近窗触碰集（零命中反例）。

    Returns: 主树 Path
    """
    base = Path(_mkdtemp("msa-scene-"))
    repo = base / "proj"
    repo.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", cwd=repo)
    (repo / "a.tsx").write_text("base", encoding="utf-8")
    (repo / "b.tsx").write_text("base", encoding="utf-8")
    (repo / ".gitignore").write_text(".fenix/\n", encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "init", cwd=repo)
    if with_local_identity:
        subprocess.run(["git", "config", "user.name", "t"], cwd=str(repo), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(repo), check=True, capture_output=True)
        # 近窗提交：作者=配置身份（读仓库 config，非 -c 注入），触碰 a.tsx
        (repo / "a.tsx").write_text("session commit", encoding="utf-8")
        _git_as_configured("add", "-A", cwd=repo)
        _git_as_configured("commit", "-q", "-m", "session work", cwd=repo)
    # 主树未提交直改（散件 WIP）
    (repo / "a.tsx").write_text("interactive session wip", encoding="utf-8")
    return repo


def _make_empty_home():
    """空 HOME 临时目录（探测源缺失现场：无全局 git 身份、无 transcript）。"""
    return Path(_mkdtemp("msa-home-"))


def _write_transcript(repo: Path, body: str, age_seconds: float = 0.0, name="s1.jsonl") -> Path:
    """在被重定向的 HOME 下写交互会话 transcript（Claude Code 惯例布局）。"""
    home = Path(os.environ["HOME"])
    tdir = home / ".claude" / "projects" / str(repo).replace("/", "-")
    tdir.mkdir(parents=True, exist_ok=True)
    p = tdir / name
    p.write_text(body, encoding="utf-8")
    if age_seconds:
        ts = time.time() - age_seconds
        os.utime(p, (ts, ts))
    return p


class TestWipOccupantInfoSessionForm(unittest.TestCase):
    """1.2：WipOccupantInfo 会话归因形态与 describe/to_dict 文案。"""

    def _session_info(self):
        return WipOccupantInfo(
            True,
            [{
                "run_ids": [], "spec": "", "branch": "",
                "worktree": "/tmp/proj",
                "files": ["a.tsx"],
                "kind": "interactive-session",
                "session": {
                    "identity": "t <t@t>",
                    "signals": ["recent-commit-path-intersection"],
                    "last_commit": "abcd1234 session work",
                },
            }],
            ["a.tsx"],
            source=WipOccupantInfo.SOURCE_MAINTREE_SESSION,
        )

    def test_session_form_predicates_and_run_ids(self):
        info = self._session_info()
        self.assertTrue(info.holder)
        self.assertTrue(info.is_session_attribution())
        self.assertEqual(info.occupant_kind(), "interactive-session")
        # 会话归因无 run_ids：终态回调注册自然缺席（defer 消费侧契约）
        self.assertEqual(info.holder_run_ids(), [])

    def test_session_describe_carries_clue_not_blind_spot(self):
        text = self._session_info().describe()
        self.assertIn("占用者=主树活交互会话", text)
        self.assertIn("t <t@t>", text)
        self.assertIn("recent-commit-path-intersection", text)
        self.assertIn("命中1文件", text)
        self.assertIn("只读探测归因，非无主盲区", text)
        self.assertNotIn("无主陈旧 WIP", text)

    def test_to_dict_carries_occupant_kind(self):
        d = self._session_info().to_dict()
        self.assertEqual(d["occupant_kind"], "interactive-session")
        self.assertEqual(d["source"], WipOccupantInfo.SOURCE_MAINTREE_SESSION)
        # 深拷贝契约不回退：台账快照与原对象断开引用
        d["holders"][0]["files"].append("mutated")
        self.assertEqual(self._session_info().holders[0]["files"], ["a.tsx"])

    def test_lane_and_orphan_kinds_unchanged(self):
        lane = WipOccupantInfo(
            True,
            [{"run_ids": ["impl-x-1"], "spec": "x", "branch": "fenix/x",
              "worktree": "/w", "files": ["a.tsx"]}],
            ["a.tsx"],
        )
        self.assertEqual(lane.occupant_kind(), "inflight-lane")
        self.assertFalse(lane.is_session_attribution())
        self.assertIn("占用者=在飞车道", lane.describe())
        orphan = WipOccupantInfo(False, [], ["a.tsx"])
        self.assertEqual(orphan.occupant_kind(), "orphan")
        self.assertIn("无主陈旧 WIP", orphan.describe())
        self.assertIn(WipOccupantInfo.BLIND_SPOT_NOTE, orphan.describe())

    def test_blind_spot_note_updated_keeps_frozen_fragments(self):
        note = WipOccupantInfo.BLIND_SPOT_NOTE
        # 文案同步（1.2）：会话探测补充归因入注记；既有冻结断言子串不回退
        self.assertIn("分支 diff 必零命中", note)
        self.assertIn("admin/人工会话", note)
        self.assertIn("maintree-interactive-session", note)


class TestProbeRecentCommitSource(unittest.TestCase):
    """1.1 候选②：git 最近提交人启发（身份 + 近窗 + 路径交三重判据）。"""

    def test_hit_attributes_to_session(self):
        repo = _make_session_repo()
        probe = _WmProbe(repo)
        info = probe.identify_wip_occupant(["a.tsx"], [])
        self.assertTrue(info.holder, "身份一致的近窗提交触碰集命中 MUST 判会话占用者")
        self.assertTrue(info.is_session_attribution())
        self.assertEqual(info.source, WipOccupantInfo.SOURCE_MAINTREE_SESSION)
        self.assertEqual(len(info.holders), 1)
        h = info.holders[0]
        self.assertEqual(h["kind"], "interactive-session")
        self.assertEqual(h["files"], ["a.tsx"])
        self.assertEqual(h["run_ids"], [])
        clue = h["session"]
        self.assertEqual(clue["identity"], "t <t@t>")
        self.assertIn("recent-commit-path-intersection", clue["signals"])
        self.assertTrue(clue["last_commit"])
        self.assertIn("占用者=主树活交互会话", info.describe())

    def test_zero_hit_when_paths_not_intersected(self):
        """散件不在近窗提交触碰集 → 零命中（仅「近期有提交」不构成命中）。"""
        repo = _make_session_repo()
        probe = _WmProbe(repo)
        info = probe.identify_wip_occupant(["b.tsx"], [])
        self.assertFalse(info.holder)
        self.assertIn("无主", info.describe())

    def test_source_missing_when_identity_unconfigured(self):
        """身份未配置（本仓无配置 + 空 HOME 无全局）→ 源缺失 fail-open 回无主。"""
        repo = _make_session_repo(with_local_identity=False)
        with mock.patch.dict(os.environ, {"HOME": str(_make_empty_home())}):
            probe = _WmProbe(repo)
            info = probe.identify_wip_occupant(["a.tsx"], [])
        self.assertFalse(info.holder)


class TestProbeTranscriptSource(unittest.TestCase):
    """1.1 候选③：transcript 活跃信号（活跃窗 + 散件路径提及双判据）。"""

    def _repo_no_identity(self):
        """无本仓身份的仓（HOME 同时置空 → 候选②必缺席，单测候选③）。"""
        repo = _make_session_repo(with_local_identity=False)
        home = _make_empty_home()
        patcher = mock.patch.dict(os.environ, {"HOME": str(home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        return repo

    def test_hit_when_active_transcript_mentions_path(self):
        repo = self._repo_no_identity()
        _write_transcript(
            repo,
            f'{{"tool_input": {{"file_path": "{repo}/a.tsx"}}}}\n',
        )
        info = _WmProbe(repo).identify_wip_occupant(["a.tsx"], [])
        self.assertTrue(info.holder, "活跃 transcript 提及散件路径 MUST 判会话占用者")
        self.assertTrue(info.is_session_attribution())
        clue = info.holders[0]["session"]
        self.assertIn("transcript-active+path-mention", clue["signals"])
        self.assertEqual(info.holders[0]["files"], ["a.tsx"])
        self.assertTrue(clue.get("transcript"))

    def test_stale_transcript_not_hit(self):
        """transcript 不在活跃窗（2h 未写）→ 零命中。"""
        repo = self._repo_no_identity()
        _write_transcript(repo, f"mention {repo}/a.tsx\n", age_seconds=2 * 3600)
        self.assertFalse(_WmProbe(repo).identify_wip_occupant(["a.tsx"], []).holder)

    def test_active_without_path_mention_not_hit(self):
        """活跃但不提及散件路径（工作范围零交叠）→ 零命中（相关性判据）。"""
        repo = self._repo_no_identity()
        _write_transcript(repo, "discussing unrelated.txt only\n")
        self.assertFalse(_WmProbe(repo).identify_wip_occupant(["a.tsx"], []).holder)

    def test_transcript_dir_absent_is_source_missing(self):
        """transcript 目录不存在 → 源缺失，行为与现状一致（回无主）。"""
        repo = self._repo_no_identity()
        self.assertFalse(_WmProbe(repo).identify_wip_occupant(["a.tsx"], []).holder)


class TestStrayWipSessionDowngrade(unittest.TestCase):
    """2.1：盘点侧降级 info 留痕 + admin.maintree_session_attribution_action 回退。"""

    def _sweeper(self, repo, grace=30.0, action=None):
        admin = {"maintree_stray_wip_grace_minutes": grace}
        if action is not None:
            admin["maintree_session_attribution_action"] = action
        from core.worktree_manager.stray_wip import MainTreeStrayWipSweeper

        return MainTreeStrayWipSweeper(
            repo, _WmProbe(repo), config={"admin": admin}, logger=None,
        )

    def _stale_alerts(self, repo):
        return [
            r for r in AdminStore(repo).read_all()
            if r.get("kind") == SIGNAL and r.get("signal_type") == "maintree_stray_wip_stale"
        ]

    def test_default_downgrades_to_info_without_major(self):
        """缺省 info：会话归因散件降级留痕，不派 major 不建档计时。"""
        repo = _make_session_repo()
        sw = self._sweeper(repo, grace=0.0)
        # grace=0：若视同无主会立即告警——降级形态必须零告警
        r = sw.sweep()
        self.assertEqual(r["status"], "session-attributed")
        self.assertIn("recent-commit-path-intersection", r["session_signals"])
        self.assertEqual(r["files"], ["a.tsx"])
        self.assertEqual(sw._registry, {})
        self.assertEqual(self._stale_alerts(repo), [])
        # 重复盘点仍降级（无计时累积）
        r2 = sw.sweep()
        self.assertEqual(r2["status"], "session-attributed")
        self.assertEqual(self._stale_alerts(repo), [])

    def test_keep_falls_back_to_orphan_grace_flow(self):
        """keep=现状行为：视同零命中走无主宽限升级（grace=0 即告警）。"""
        repo = _make_session_repo()
        sw = self._sweeper(repo, grace=0.0, action="keep")
        r = sw.sweep()
        self.assertEqual(r["status"], "alerted")
        alerts = self._stale_alerts(repo)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["severity"], "major")
        # evidence 仍透传 describe() 会话线索（不静默吞线索）
        self.assertIn("主树活交互会话", alerts[0].get("evidence") or "")

    def test_invalid_action_guard_falls_back_to_keep(self):
        """非法配置值守卫回退 keep（配置事故 MUST NOT 静默吞 major）。"""
        repo = _make_session_repo()
        sw = self._sweeper(repo, grace=0.0, action="bogus")
        self.assertEqual(sw.sweep()["status"], "alerted")
        self.assertEqual(len(self._stale_alerts(repo)), 1)

    def test_session_attribution_action_reader(self):
        from core.worktree_manager.stray_wip import session_attribution_action

        self.assertEqual(session_attribution_action({}), "info")
        self.assertEqual(
            session_attribution_action({"admin": {"maintree_session_attribution_action": "info"}}),
            "info",
        )
        self.assertEqual(
            session_attribution_action({"admin": {"maintree_session_attribution_action": "keep"}}),
            "keep",
        )
        # 显式 None＝未配置（ConfigLoader.get 视同缺失）→ 缺省 info
        self.assertEqual(
            session_attribution_action({"admin": {"maintree_session_attribution_action": None}}),
            "info",
        )
        # 宽松归一化：大小写/首尾空白不改变合法值语义
        self.assertEqual(
            session_attribution_action({"admin": {"maintree_session_attribution_action": " INFO "}}),
            "info",
        )
        # 非法值 → keep 守卫（配置事故 MUST NOT 静默吞 major）
        for bad in ("bogus", "", 3):
            self.assertEqual(
                session_attribution_action({"admin": {"maintree_session_attribution_action": bad}}),
                "keep",
                msg=f"bad={bad!r}",
            )


class TestCodeFixSessionPassthrough(unittest.TestCase):
    """2.2：code_fix defer 消费点对会话归因的采信与同键回退。"""

    def _scene(self):
        """defer 现场：主树会话归因命中 + 可存活 defer 台账条目。"""
        repo = _make_session_repo()
        proot = Path(_mkdtemp("msa-proot-"))
        (proot / ".fenix" / "code-review").mkdir(parents=True, exist_ok=True)
        # 载体 worktree 替身：独立 git 仓（台账判活只需目录在盘 + tip 可解析）
        wt = Path(_mkdtemp("msa-wt-"))
        _git("init", "-q", cwd=wt)
        (wt / "f.txt").write_text("x", encoding="utf-8")
        _git("add", "-A", cwd=wt)
        _git("commit", "-q", "-m", "init", cwd=wt)
        tip = subprocess.run(
            ["git", "-C", str(wt), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        from core.code_fix import record_deferred_batch, load_deferred_batches

        record_deferred_batch(
            proot, ["i1"], ["i1"], wt,
            branch="fenix/spec-x-1700000000", tip_sha=tip,
            last_overlap=["a.tsx"],
        )
        runner = self._fake_runner(proot)
        runner.worktree_manager = _WmProbe(repo)
        return repo, proot, runner, load_deferred_batches(proot)[0]

    @staticmethod
    def _fake_runner(proot):
        from core.agent_runner.runner import AgentRunner

        runner = AgentRunner.__new__(AgentRunner)
        runner.project_root = Path(proot)
        runner.logger = None
        runner._running_agents = {}
        runner.config = {}
        return runner

    def _orch(self, runner, action=None, orphan_grace=None):
        from core.code_fix import CodeFixOrchestrator

        admin = {}
        if action is not None:
            admin["maintree_session_attribution_action"] = action
        if orphan_grace is not None:
            admin["mergeback_wip_orphan_grace_minutes"] = orphan_grace
        return CodeFixOrchestrator(
            runner, runner.project_root,
            config={"admin": admin} if admin else {}, logger=None,
        )

    def _orphan_alerts(self, proot):
        return [
            r for r in AdminStore(proot).read_all()
            if r.get("kind") == SIGNAL and r.get("signal_type") == "mergeback_wip_orphan_stuck"
        ]

    def test_trusted_session_attribution_holder_no_escalation(self):
        """缺省 info：采信会话归因 → owner_kind=holder、零升级、零订阅。"""
        _repo, proot, runner, entry = self._scene()
        orch = self._orch(runner)
        note = orch._coordinate_blocked_merge(
            entry, ["i1"], ["a.tsx"], "fenix/spec-x-1700000000", str(entry.get("tip_sha") or ""),
        )
        self.assertIn("占用者=主树活交互会话", note)
        from core.code_fix import load_deferred_batches

        saved = load_deferred_batches(proot)[0]
        self.assertEqual(saved.get("owner_kind"), "holder")
        self.assertIsNone(saved.get("owner_orphan_since"))
        # 会话归因无 run_ids：终态回调零订阅（轮询兜底在场）
        self.assertEqual(runner._run_terminal_callback_table(), {})
        self.assertEqual(self._orphan_alerts(proot), [])

    def test_keep_treats_session_attribution_as_orphan(self):
        """keep=视同零命中走现状 orphan 宽限升级流（同键约束对称）。"""
        _repo, proot, runner, entry = self._scene()
        orch = self._orch(runner, action="keep", orphan_grace=0)
        note = orch._coordinate_blocked_merge(
            entry, ["i1"], ["a.tsx"], "fenix/spec-x-1700000000", str(entry.get("tip_sha") or ""),
        )
        self.assertIn("主树活交互会话", note)
        self.assertIn("keep", note)
        from core.code_fix import load_deferred_batches

        saved = load_deferred_batches(proot)[0]
        self.assertEqual(saved.get("owner_kind"), "orphan")
        self.assertTrue(saved.get("owner_orphan_since"))
        # 宽限耗尽 → 一次性 major 升级，evidence 透传会话线索与盲区注记
        alerts = self._orphan_alerts(proot)
        self.assertEqual(len(alerts), 1)
        evidence = alerts[0].get("evidence") or ""
        self.assertIn("主树活交互会话", evidence)
        self.assertIn(WipOccupantInfo.BLIND_SPOT_NOTE, evidence)


if __name__ == "__main__":
    unittest.main()
