"""add-mergeback-wip-active-coordination 单测（tasks.md 3.1-3.4）。

覆盖：
- 3.1 overlap + 在飞持有者 → 识别命中；持有者 run 终态事件到达后合回秒级
  重试成功（不等到轮询周期）
- 3.2 overlap + 无主 → 宽限内不告警；宽限耗尽发出 major 告警（含文件与
  证据）、批不丢弃、主树零触碰
- 3.3 注册监听时 run 已终态 → 立即触发重试（不依赖后续事件）
- 3.4 无 overlap → 合回路径与现状逐字一致（零新增开销）
"""

import json
import subprocess
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

# /tmp 可能被外部清扫进程周期性清空（test_code_fix 同款规避）。统一用仓库内
# .history/tmp（gitignored），MUST NOT 改写全局 tempfile.tempdir。
_HISTORY_TMP = Path(__file__).resolve().parent.parent / ".history" / "tmp"
_HISTORY_TMP.mkdir(parents=True, exist_ok=True)


def _mkdtemp(prefix: str) -> str:
    return tempfile.mkdtemp(prefix=prefix, dir=str(_HISTORY_TMP))


class _FakeLogger:
    """双参形态 logger（component, msg），收集 warning 供断言。"""

    def __init__(self):
        self.warnings = []
        self.infos = []

    def _rec(self, sink, component, msg, extra=None):
        sink.append(f"{component}: {msg}")

    def debug(self, component, msg, extra=None):
        pass

    def info(self, component, msg, extra=None):
        self._rec(self.infos, component, msg, extra)

    def warning(self, component, msg, extra=None):
        self._rec(self.warnings, component, msg, extra)

    def error(self, component, msg, extra=None):
        self._rec(self.warnings, component, msg, extra)


def _git(*args, cwd, check=True):
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=str(cwd), check=check, capture_output=True, text=True,
    )


def _git_init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", cwd=path)
    return path


def _make_main_repo_with_holder(spec: str = "spec-x", ts: int = 1700000000):
    """主树仓 + 在飞车道 worktree 分支场景（3.1/3.2 识别的真实 git 现场）。

    - 主树 `a.tsx` 有未提交修改（WIP overlap 的主树侧）；
    - worktree 目录名 ``impl-<spec>-<ts>``，分支 ``fenix/<spec>-<ts>``，
      分支上提交了对 `a.tsx` 的修改（车道分支改动侧）；
    - `b.tsx` 全场无改动（供无主/零命中反例）。

    独立基目录：worktree 目录名含固定 ts，MUST 与主树同置于每次测试独立的
    基目录下，否则多个测试在同一 `_HISTORY_TMP` 根下互撞同名 worktree 路径。

    Returns: (主树 Path, worktree Path, 分支名)
    """
    base = Path(_mkdtemp("wipc-scene-"))
    repo = _git_init_repo(base / "main")
    (repo / "a.tsx").write_text("base", encoding="utf-8")
    (repo / "b.tsx").write_text("base", encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "init", cwd=repo)
    wt_dir = base / f"impl-{spec}-{ts}"
    branch = f"fenix/{spec}-{ts}"
    _git("worktree", "add", "-b", branch, str(wt_dir), "HEAD", cwd=repo)
    (wt_dir / "a.tsx").write_text("branch change", encoding="utf-8")
    _git("commit", "-aq", "-m", "branch wip", cwd=wt_dir)
    # 主树未提交修改（overlap 的主树侧）
    (repo / "a.tsx").write_text("main wip", encoding="utf-8")
    return repo, wt_dir, branch


class _IdentifyProbe:
    """identify_wip_occupant 探针壳：混入 mergeback + queries mixin。

    identify_wip_occupant/_worktree_name_branch_pairs/_branch_changed_files
    只依赖 project_root 与 _wt_name_matches_spec（queries 静态方法），无需
    完整 WorktreeManager 装配。
    """

    from core.worktree_manager.mergeback import G4MergebackMixin as _G4
    from core.worktree_manager.queries import G8QueryMixin as _G8

    class Inner(_G4, _G8):
        def __init__(self, root):
            self.project_root = Path(root)

    def __init__(self, root):
        self.impl = self.Inner(root)

    def __getattr__(self, name):
        return getattr(self.impl, name)


class _FakeWM:
    """fake worktree_manager：merge_back/cleanup 记录调用，结果可编排。"""

    def __init__(self, merge_results=None):
        self.merge_calls = []
        self.cleanup_calls = []
        self._merge_results = list(merge_results or [])

    def merge_back(self, wt_path):
        self.merge_calls.append(str(wt_path))
        if self._merge_results:
            info = self._merge_results.pop(0)
        else:
            info = types.SimpleNamespace(success=True, error="")
        return info

    def cleanup(self, wt_path, success=True):
        self.cleanup_calls.append((str(wt_path), success))


def _make_project_root() -> Path:
    td = Path(_mkdtemp("wipc-proot-"))
    (td / ".fenix" / "code-review").mkdir(parents=True, exist_ok=True)
    return td


def _make_runner(proot: Path, running_ids=()) -> object:
    """真实 AgentRunner（绕 __init__）+ 测试所需最小态（对齐生产单键原子语义）。"""
    from core.agent_runner.runner import AgentRunner

    runner = AgentRunner.__new__(AgentRunner)
    runner.project_root = Path(proot)
    runner.logger = _FakeLogger()
    runner._running_agents = {rid: object() for rid in running_ids}
    return runner


_CFG_ON = {
    "admin": {
        "code_review_fix": {"enabled": True, "batch_size": 20},
    }
}


def _record_deferred(proot: Path, wt_dir: Path, overlap, item_id="i1"):
    """落一条真实可存活的 defer 台账条目，返回台账条目 dict。"""
    from core.code_fix import record_deferred_batch, load_deferred_batches

    tip = subprocess.run(
        ["git", "-C", str(wt_dir), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    record_deferred_batch(
        proot, [item_id], [item_id], wt_dir,
        branch="fenix/spec-x-1700000000", tip_sha=tip,
        last_overlap=list(overlap),
    )
    return load_deferred_batches(proot)[0]


class TestOccupantIdentification(unittest.TestCase):
    """3.1a：overlap + 在飞持有者 → 识别命中（run/spec/分支可追溯）。"""

    def test_holder_identified_by_branch_diff(self):
        repo, wt_dir, branch = _make_main_repo_with_holder()
        probe = _IdentifyProbe(repo)
        info = probe.identify_wip_occupant(
            ["a.tsx"], ["impl-spec-x-1700000000-a1"]
        )
        self.assertTrue(info.holder, "在飞车道分支改动集命中 MUST 判为在飞持有者")
        self.assertEqual(len(info.holders), 1)
        h = info.holders[0]
        self.assertEqual(h["spec"], "spec-x")
        self.assertEqual(h["branch"], branch)
        self.assertIn("impl-spec-x-1700000000-a1", h["run_ids"])
        self.assertEqual(h["files"], ["a.tsx"])
        self.assertIn("占用者=在飞车道", info.describe())
        self.assertIn("impl-spec-x-1700000000-a1", info.holder_run_ids())

    def test_holder_identified_via_codefix_bridge(self):
        """code-fix 车道（固定 spec 名建树）经桥接同样可识别（D1 覆盖 code-fix）。"""
        repo, _, _ = _make_main_repo_with_holder(spec="code-review-fix")
        probe = _IdentifyProbe(repo)
        info = probe.identify_wip_occupant(
            ["a.tsx"], ["code-fix-1700000001"]
        )
        self.assertTrue(info.holder, "code-fix 车道分支命中 MUST 判为在飞持有者")
        self.assertEqual(info.holders[0]["spec"], "code-review-fix")

    def test_orphan_when_no_lane_hits(self):
        """分支改动集与 overlap 零命中 → 无主（识别结果可追溯）。"""
        repo, _, _ = _make_main_repo_with_holder()
        probe = _IdentifyProbe(repo)
        # b.tsx 不在任何在飞车道分支改动集
        info = probe.identify_wip_occupant(
            ["b.tsx"], ["impl-spec-x-1700000000-a1"]
        )
        self.assertFalse(info.holder, "零命中 MUST 判为无主陈旧 WIP")
        self.assertIn("无主", info.describe())
        # D1 已知盲区注记必须随识别结果留痕
        self.assertIn("分支 diff 必零命中", info.describe())
        self.assertIn("admin/人工会话", info.to_dict()["blind_spot_note"])

    def test_orphan_when_no_inflight_runs(self):
        repo, _, _ = _make_main_repo_with_holder()
        probe = _IdentifyProbe(repo)
        info = probe.identify_wip_occupant(["a.tsx"], [])
        self.assertFalse(info.holder)


class TestEventDrivenRetry(unittest.TestCase):
    """3.1b：持有者 run 终态事件到达后合回秒级重试成功（不等到轮询周期）。"""

    def test_holder_terminal_event_triggers_merge_retry_immediately(self):
        repo, wt_dir, branch = _make_main_repo_with_holder()
        proot = _make_project_root()
        runner = _make_runner(
            proot, running_ids=["impl-spec-x-1700000000-a1"]
        )
        fake_wm = _FakeWM(merge_results=[types.SimpleNamespace(success=True, error="")])
        # 识别走真实 git 现场（探针实例的识别方法挂到 fake wm 上）
        probe = _IdentifyProbe(repo)
        fake_wm.identify_wip_occupant = probe.identify_wip_occupant
        runner.worktree_manager = fake_wm
        from core.code_fix import CodeFixOrchestrator, load_deferred_batches

        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=None)
        _record_deferred(proot, wt_dir, ["a.tsx"])
        entry = load_deferred_batches(proot)[0]

        # 持有者在飞：协调即注册终态监听（不立即触发）
        note = orch._coordinate_blocked_merge(
            entry, ["i1"], ["a.tsx"], branch,
            str(entry.get("tip_sha") or ""),
        )
        self.assertIn("占用者=在飞车道", note)
        table = runner._run_terminal_callback_table()
        self.assertIn("impl-spec-x-1700000000", table, "持有者 base run MUST 已注册终态监听")

        # 终态事件到达：秒级触发重试（不等待任何轮询周期）
        t0 = time.time()
        runner._fire_run_terminal_callbacks("impl-spec-x-1700000000-a1")
        elapsed = time.time() - t0
        self.assertLess(elapsed, 5, "终态事件触发的重试 MUST 秒级返回（不进轮询等待）")
        self.assertEqual(len(fake_wm.merge_calls), 1, "终态到达 MUST 立即重试合回")
        self.assertEqual(fake_wm.merge_calls[0], str(wt_dir))
        # 合回成功 → 批核销出台账
        self.assertEqual(load_deferred_batches(proot), [])
        # 事件消费即摘除监听（无泄漏）
        self.assertNotIn("impl-spec-x-1700000000", runner._run_terminal_callback_table())

    def test_callback_yields_when_lock_held(self):
        """锁占用守卫：不可重入 Lock 下的注册即触发路径 MUST 让位（防自锁死）。

        ``_retry_one_deferred`` 的注册点位于 checkpoint 的 ``self._lock`` 段内
        ——若「run 已终态→立即触发」在此时同步重入 ``checkpoint()`` 即自锁死。
        锁占用时回调 MUST 让位；锁空闲时正常投递 checkpoint。
        """
        proot = _make_project_root()
        runner = _make_runner(proot)
        from core.code_fix import CodeFixOrchestrator

        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=None)
        called = []
        orch.checkpoint = lambda *a, **k: called.append(1)
        cb = orch._make_holder_retry_callback("fenix/spec-x-1700000000")
        with orch._lock:
            cb()
        self.assertEqual(called, [], "锁占用时 MUST 让位（不可重入 Lock，重入即死锁）")
        cb()
        self.assertEqual(called, [1], "锁空闲时 MUST 投递 checkpoint")

    def test_blocked_retry_recoordinates_and_records_owner(self):
        """轮询兜底重试仍被挡 → 识别结果随台账 owner_* 字段与进度留痕。"""
        repo, wt_dir, branch = _make_main_repo_with_holder()
        proot = _make_project_root()
        runner = _make_runner(
            proot, running_ids=["impl-spec-x-1700000000-a1"]
        )
        blocked = types.SimpleNamespace(
            success=False, error="blocked", wip_gate_blocked=True,
            wip_overlap=["a.tsx"],
        )
        fake_wm = _FakeWM(merge_results=[blocked])
        probe = _IdentifyProbe(repo)
        fake_wm.identify_wip_occupant = probe.identify_wip_occupant
        runner.worktree_manager = fake_wm
        from core.code_fix import CodeFixOrchestrator, load_deferred_batches, read_progress

        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=None)
        _record_deferred(proot, wt_dir, ["a.tsx"])
        entry = load_deferred_batches(proot)[0]

        hit, msg = orch._retry_one_deferred(fake_wm, entry)
        self.assertEqual(hit, 0)
        self.assertIn("占用者=在飞车道", msg, "识别摘要 MUST 并入结果文案")
        rec = read_progress(proot)
        self.assertIn("占用者=在飞车道", rec.get("current") or "")
        saved = load_deferred_batches(proot)[0]
        self.assertEqual(saved.get("owner_kind"), "holder")
        self.assertTrue(saved.get("owner_holders"))
        self.assertIn(
            "impl-spec-x-1700000000", runner._run_terminal_callback_table(),
            "重试被挡仍 MUST 注册持有者终态监听",
        )


class TestOrphanGraceEscalation(unittest.TestCase):
    """3.2：overlap + 无主 → 宽限内不告警；耗尽发 major 告警、批不丢弃、主树零触碰。"""

    def _scenario(self, grace_minutes=30):
        repo, wt_dir, branch = _make_main_repo_with_holder()
        proot = _make_project_root()
        runner = _make_runner(proot)  # 无在飞 run → 无主
        fake_wm = _FakeWM()
        probe = _IdentifyProbe(repo)
        fake_wm.identify_wip_occupant = probe.identify_wip_occupant
        runner.worktree_manager = fake_wm
        from core.code_fix import CodeFixOrchestrator

        cfg = {
            "admin": {
                "code_review_fix": {"enabled": True, "batch_size": 20},
                "mergeback_wip_orphan_grace_minutes": grace_minutes,
            }
        }
        orch = CodeFixOrchestrator(runner, proot, config=cfg, logger=None)
        return repo, wt_dir, branch, proot, orch

    def _alerts(self, proot: Path) -> list:
        path = proot / ".fenix" / "admin_alerts.json"
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return [r for r in data if isinstance(r, dict)]

    def _git_state(self, repo: Path) -> tuple:
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=str(repo),
            capture_output=True, text=True,
        ).stdout
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(repo),
            capture_output=True, text=True,
        ).stdout.strip()
        return status, head

    def test_no_alert_within_grace(self):
        repo, wt_dir, branch, proot, orch = self._scenario(grace_minutes=30)
        from core.code_fix import load_deferred_batches

        _record_deferred(proot, wt_dir, ["a.tsx"])
        entry = load_deferred_batches(proot)[0]
        note = orch._coordinate_blocked_merge(entry, ["i1"], ["a.tsx"], branch, "")
        self.assertIn("无主", note)
        self.assertIn("宽限", note)
        # 宽限内不告警
        self.assertEqual(
            [a for a in self._alerts(proot)
             if a.get("signal_type") == "mergeback_wip_orphan_stuck"],
            [], "宽限内 MUST NOT 发出无主升级告警",
        )
        # 宽限计时随台账留痕、识别结果留痕
        saved = load_deferred_batches(proot)[0]
        self.assertEqual(saved.get("owner_kind"), "orphan")
        self.assertTrue(saved.get("owner_orphan_since"))
        # 无主不注册事件监听（无可订阅对象）
        self.assertEqual(
            orch._agent_runner._run_terminal_callback_table(), {},
            "无主 MUST NOT 注册终态监听",
        )

    def test_alert_fires_after_grace_exhausted(self):
        repo, wt_dir, branch, proot, orch = self._scenario(grace_minutes=30)
        from core.code_fix import (
            _patch_deferred_entry, load_deferred_batches,
        )

        _record_deferred(proot, wt_dir, ["a.tsx"])
        # 宽限计时起点回拨 31 分钟（> 30 分钟宽限）
        stale = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 31 * 60))
        _patch_deferred_entry(proot, ["i1"], owner_orphan_since=stale)
        entry = load_deferred_batches(proot)[0]

        status_before, head_before = self._git_state(repo)
        note = orch._coordinate_blocked_merge(entry, ["i1"], ["a.tsx"], branch, "")
        self.assertIn("宽限已耗尽", note)
        alerts = [
            a for a in self._alerts(proot)
            if a.get("signal_type") == "mergeback_wip_orphan_stuck"
        ]
        self.assertEqual(len(alerts), 1, "宽限耗尽 MUST 恰发出一次 major 告警")
        alert = alerts[0]
        self.assertEqual(alert.get("severity"), "major")
        self.assertIn("a.tsx", alert.get("evidence") or "", "告警 MUST 附重叠文件清单")
        self.assertIn("盲区", alert.get("evidence") or "", "告警 MUST 附 D1 已知盲区注记")
        self.assertIn("无 spec 可重派", alert.get("recommended_action") or "",
                      "处置指引 MUST 按批语义适配")
        # 批不丢弃（保持「保留待自动合回」语义），升级只记一次
        saved = load_deferred_batches(proot)
        self.assertEqual(len(saved), 1, "升级 MUST NOT 丢弃/降级批")
        self.assertTrue(saved[0].get("owner_escalated_at"))
        # 主树零触碰
        status_after, head_after = self._git_state(repo)
        self.assertEqual(status_before, status_after)
        self.assertEqual(head_before, head_after)
        # 二次协调不重复升级（一次性语义）
        entry2 = load_deferred_batches(proot)[0]
        orch._coordinate_blocked_merge(entry2, ["i1"], ["a.tsx"], branch, "")
        alerts2 = [
            a for a in self._alerts(proot)
            if a.get("signal_type") == "mergeback_wip_orphan_stuck"
        ]
        self.assertEqual(len(alerts2), 1, "升级 MUST 只发一次（owner_escalated_at 去重）")

    def test_grace_zero_escalates_immediately(self):
        """宽限 0 = 耗尽即升级（配置可收紧；非法负值回退 30 由解析器保证）。"""
        repo, wt_dir, branch, proot, orch = self._scenario(grace_minutes=0)
        from core.code_fix import load_deferred_batches

        _record_deferred(proot, wt_dir, ["a.tsx"])
        entry = load_deferred_batches(proot)[0]
        orch._coordinate_blocked_merge(entry, ["i1"], ["a.tsx"], branch, "")
        alerts = [
            a for a in self._alerts(proot)
            if a.get("signal_type") == "mergeback_wip_orphan_stuck"
        ]
        self.assertEqual(len(alerts), 1, "宽限 0 时首次识别即应升级")
        self.assertEqual(alerts[0].get("severity"), "major")

    def test_holder_transition_resets_orphan_clock(self):
        """识别结果变化（无主→有主）：宽限计时清零（design D2 轮询随之更新）。"""
        repo, wt_dir, branch = _make_main_repo_with_holder()
        proot = _make_project_root()
        from core.code_fix import (
            CodeFixOrchestrator, _patch_deferred_entry, load_deferred_batches,
        )

        runner = _make_runner(proot)  # 先无在飞 → 无主
        fake_wm = _FakeWM()
        fake_wm.identify_wip_occupant = _IdentifyProbe(repo).identify_wip_occupant
        runner.worktree_manager = fake_wm
        cfg = {
            "admin": {
                "code_review_fix": {"enabled": True, "batch_size": 20},
                "mergeback_wip_orphan_grace_minutes": 30,
            }
        }
        orch = CodeFixOrchestrator(runner, proot, config=cfg, logger=None)
        _record_deferred(proot, wt_dir, ["a.tsx"])
        # 宽限计时进行中（5 分钟 < 30 分钟宽限，不告警）
        recent = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 5 * 60))
        _patch_deferred_entry(proot, ["i1"], owner_orphan_since=recent)
        entry = load_deferred_batches(proot)[0]
        note = orch._coordinate_blocked_merge(entry, ["i1"], ["a.tsx"], branch, "")
        self.assertIn("无主", note)
        self.assertEqual(
            [a for a in self._alerts(proot)
             if a.get("signal_type") == "mergeback_wip_orphan_stuck"],
            [], "宽限内 MUST NOT 升级",
        )
        # 持有者出现在飞：宽限计时清零 + 注册监听
        runner._running_agents = {"impl-spec-x-1700000000-a1": object()}
        entry2 = load_deferred_batches(proot)[0]
        note = orch._coordinate_blocked_merge(entry2, ["i1"], ["a.tsx"], branch, "")
        self.assertIn("在飞车道", note)
        saved = load_deferred_batches(proot)[0]
        self.assertIsNone(saved.get("owner_orphan_since"), "无主→有主 MUST 清零宽限计时")


class TestRegisterAfterTerminal(unittest.TestCase):
    """3.3：注册监听时 run 已终态 → 立即触发（不依赖后续事件）。"""

    _RID = "impl-spec-x-1700000000-a1"

    def _runner_with_terminal_file(self, proot: Path, running_ids=()):
        runner = _make_runner(proot, running_ids=running_ids)
        runs_dir = proot / ".fenix" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        (runs_dir / f"{self._RID}.jsonl").write_text(
            json.dumps({"type": "result", "result": "done"}) + "\n",
            encoding="utf-8",
        )
        return runner

    def test_register_after_terminal_fires_immediately(self):
        proot = _make_project_root()
        runner = self._runner_with_terminal_file(proot)
        fired = []
        runner.register_run_terminal_callback(
            self._RID, lambda: fired.append(1), subscriber="t"
        )
        self.assertEqual(fired, [1], "run 已终态时注册 MUST 立即触发（不依赖后续事件）")
        self.assertNotIn(
            "impl-spec-x-1700000000", runner._run_terminal_callback_table(),
            "立即触发后 MUST 消费注册项（防监听泄漏）",
        )

    def test_inflight_run_registers_without_immediate_fire(self):
        """在飞 run（注册表在场）不因旧 attempt 终态文件误触发；终态收口才触发。"""
        proot = _make_project_root()
        runner = self._runner_with_terminal_file(proot, running_ids=[self._RID])
        fired = []
        runner.register_run_terminal_callback(
            self._RID, lambda: fired.append(1), subscriber="t"
        )
        self.assertEqual(fired, [], "在飞 run MUST NOT 立即触发")
        runner._fire_run_terminal_callbacks(self._RID)
        self.assertEqual(fired, [1], "终态收口 MUST 触发已注册回调")

    def test_attempt_id_normalized_to_base(self):
        """attempt 形态 run_id 注册/触发都归一到 base（a1/r1 后缀剥离）。"""
        proot = _make_project_root()
        runner = _make_runner(proot, running_ids=[self._RID])
        fired = []
        runner.register_run_terminal_callback(
            "impl-spec-x-1700000000", lambda: fired.append(1), subscriber="t"
        )
        self.assertEqual(fired, [])
        runner._fire_run_terminal_callbacks("impl-spec-x-1700000000-r1")
        self.assertEqual(fired, [1])

    def test_subscriber_overwrite_no_accumulation(self):
        """同 run 同订阅方重复注册覆盖（轮询重复注册不累积）。"""
        proot = _make_project_root()
        runner = self._runner_with_terminal_file(proot, running_ids=[self._RID])
        fired = []
        for i in range(3):
            runner.register_run_terminal_callback(
                self._RID, lambda v=i: fired.append(v), subscriber="t"
            )
        runner._fire_run_terminal_callbacks(self._RID)
        self.assertEqual(fired, [2], "重复注册覆盖，只保留最后回调且只触发一次")

    def test_callback_exception_does_not_break_others(self):
        proot = _make_project_root()
        runner = self._runner_with_terminal_file(proot, running_ids=[self._RID])
        fired = []

        def _boom():
            raise RuntimeError("boom")

        runner.register_run_terminal_callback(self._RID, _boom, subscriber="bad")
        runner.register_run_terminal_callback(
            self._RID, lambda: fired.append(1), subscriber="good"
        )
        runner._fire_run_terminal_callbacks(self._RID)
        self.assertEqual(fired, [1], "单回调异常 MUST NOT 阻断其余回调")


class TestNoOverlapZeroOverhead(unittest.TestCase):
    """3.4：无 overlap → 合回路径与现状逐字一致（零新增开销）。"""

    def test_identify_short_circuits_without_subprocess(self):
        """空 overlap：识别零 git 调用、零识别开销（spec：无 overlap 零变化）。"""
        repo, _, _ = _make_main_repo_with_holder()
        probe = _IdentifyProbe(repo)
        import core.worktree_manager.mergeback as mb

        with mock.patch.object(
            mb.subprocess, "run",
            side_effect=AssertionError("无 overlap MUST NOT 发起任何 git 探测"),
        ):
            info = probe.identify_wip_occupant([], ["impl-spec-x-1700000000-a1"])
        self.assertFalse(info.holder)

    def test_success_merge_path_unchanged_no_subscription(self):
        """合回成功路径（无 overlap）：行为与现状一致——合回一次、核销出台账、
        零识别订阅开销（无 owner_* 字段、终态回调表为空）。"""
        proot = _make_project_root()
        wt_dir = _git_init_repo(Path(_mkdtemp("wipc-wt-")))
        (wt_dir / "f.txt").write_text("x", encoding="utf-8")
        _git("add", "-A", cwd=wt_dir)
        _git("commit", "-q", "-m", "init", cwd=wt_dir)
        runner = _make_runner(proot)
        fake_wm = _FakeWM(merge_results=[types.SimpleNamespace(success=True, error="")])
        runner.worktree_manager = fake_wm
        from core.code_fix import (
            CodeFixOrchestrator, load_deferred_batches, _patch_deferred_entry,
        )

        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=None)
        _record_deferred(proot, wt_dir, [])
        hit, msg = orch._retry_one_deferred(fake_wm, load_deferred_batches(proot)[0])
        self.assertEqual(fake_wm.merge_calls, [str(wt_dir)], "合回照常执行一次")
        self.assertEqual(load_deferred_batches(proot), [], "成功核销出台账（现状语义）")
        self.assertEqual(
            orch._agent_runner._run_terminal_callback_table(), {},
            "无 overlap MUST 零订阅开销",
        )

    def test_coordinate_with_empty_overlap_is_noop(self):
        """空 overlap 的协调调用：零识别、零台账字段写入。"""
        repo, wt_dir, branch = _make_main_repo_with_holder()
        proot = _make_project_root()
        runner = _make_runner(proot)
        fake_wm = _FakeWM()
        fake_wm.identify_wip_occupant = _IdentifyProbe(repo).identify_wip_occupant
        runner.worktree_manager = fake_wm
        from core.code_fix import CodeFixOrchestrator, load_deferred_batches

        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=None)
        _record_deferred(proot, wt_dir, [])
        entry = load_deferred_batches(proot)[0]
        import core.worktree_manager.mergeback as mb

        with mock.patch.object(
            mb.subprocess, "run",
            side_effect=AssertionError("无 overlap MUST NOT 发起识别探测"),
        ):
            note = orch._coordinate_blocked_merge(
                entry, ["i1"], [], branch, str(entry.get("tip_sha") or "")
            )
        self.assertEqual(note, "")
        saved = load_deferred_batches(proot)[0]
        for field in ("owner_kind", "owner_holders", "owner_orphan_since",
                      "owner_escalated_at", "owner_identified_at"):
            self.assertIsNone(saved.get(field), f"无 overlap MUST NOT 写 {field}")


if __name__ == "__main__":
    unittest.main()
