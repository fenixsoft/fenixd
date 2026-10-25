"""test-knowledge-distill-resume — 蒸馏批次持久化与崩溃续跑
（evo-knowledge-distill-resume-guard 3.1-3.4）。

覆盖（R1-R4 对应 SPEC 验收）：
- R1 pending 台账：dispatch 单点落盘（含 queued_at）、损坏/非法 JSON 按空表
  fail-open 且派发不受阻、批量+交错单条并发入队不丢条目（tmp+os.replace）。
- R2 条目生命周期：批次成功收尾（含无变更）移除、_give_up 清理确认移除、
  提交失败滞留保留（todo 台账注明重启续跑接管）、门控拒绝/回填期排队不写、
  同项目积压合并为一次 run 时按 names 并集一次清除。
- R3 恢复：recover_pending 先清空台账后重派（放行条目重新落盘、门控拒绝
  条目不复活）、恢复批次经 worker 消费完成入库提交、恢复日志。
- R4 _is_idle 蒸馏维度：worker 在飞/队列非空非空闲、死台账不钉自愈、
  替身缺属性按空闲不抛异常、内部状态不可读按非空闲。

测试隔离：注入 DistillManager 替身 spawn（fake 不触真实网关）、
monkeypatch ``core.knowledge._MANAGER`` / ``_in_pytest`` / ``validate_knowledge``
（产出校验本身由 test_knowledge_e2e / test_knowledge 覆盖，本文件只验台账
生命周期）；fixture 写项目级 config.yaml 固定 ``knowledge.enabled: true``，
不受用户级配置漂移影响。
"""

import os
import subprocess
import tempfile
import threading
import time
import unittest
import shutil
from datetime import date
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from unittest import mock

import core.knowledge as kn
from core.knowledge import KNOWLEDGE_DIR, DistillManager

GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}

TODAY = date.today().isoformat()
N1 = f"{TODAY}-alpha-spec"
N2 = f"{TODAY}-beta-spec"
N3 = f"{TODAY}-gamma-spec"
N4 = f"{TODAY}-delta-spec"
N_GONE = f"{TODAY}-gone-spec"  # 归档目录不存在（门控拒绝用）
TS = "2026-10-11T00:00:00+08:00"


def _git(proot: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(proot), *args],
        env=GIT_ENV, capture_output=True, text=True, timeout=60,
    )


class _Proc0:
    """fake Popen：exit code 可配，prompt 经 communicate 首参回调（stdin 口径）。"""

    pid = -1

    def __init__(self, returncode=0, on_prompt=None):
        self.returncode = returncode
        self._on_prompt = on_prompt

    def communicate(self, prompt=None, timeout=None):
        if self._on_prompt is not None:
            self._on_prompt(prompt or "")
        return "", ""


class _GateSpawn:
    """fake spawn：首个 run 在记录提示词后阻塞在 release 上（批次保持在飞可控），
    后续 run 直通；30s 超时自动放行防用例遗忘 release 挂死。"""

    def __init__(self, returncode=0, on_prompt=None):
        self.returncode = returncode
        self._extra_on_prompt = on_prompt
        self.release = threading.Event()
        self.prompts = []  # 每轮 run 收到的提示词（合并批断言用）
        self.calls = 0

    def __call__(self, cmd, cwd, env=None):
        self.calls += 1
        return _Proc0(returncode=self.returncode, on_prompt=self._on_prompt)

    def _on_prompt(self, prompt):
        self.prompts.append(prompt)
        if self._extra_on_prompt is not None:
            self._extra_on_prompt(prompt)
        if len(self.prompts) == 1:
            self.release.wait(timeout=30)


class DistillResumeTestBase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        self.ledger_path = kn._pending_ledger_path(self.root)
        self._build_project()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _build_project(self):
        # 项目级 config 固定 knowledge.enabled: true（不随用户级配置漂移）；
        # git 仓库（_commit_output / _git_status_paths 真实路径需要）
        (self.root / ".fenix" / "logs").mkdir(parents=True)
        (self.root / ".fenix" / "config.yaml").write_text(
            "knowledge:\n  enabled: true\n", encoding="utf-8"
        )
        (self.root / KNOWLEDGE_DIR).mkdir(parents=True, exist_ok=True)
        for name in (N1, N2, N3, N4):
            (self.root / "spec" / "archive" / name).mkdir(parents=True)
        for cmd in (
            ["init", "-q"],
            ["config", "user.name", "t"],
            ["config", "user.email", "t@t"],
            ["add", "--", "."],
            ["commit", "-q", "-m", "init"],
        ):
            _git(self.root, *cmd)

    # ── 有界等待助手（worker 异步执行，禁止无界轮询）─────────────────
    def _wait_until(self, cond, timeout=15.0, interval=0.05) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return True
            time.sleep(interval)
        return False

    def _ledger_names(self) -> list:
        return [tuple(b["names"]) for b in kn._read_pending_ledger(self.root)]

    def _wait_ledger_contains(self, *names) -> list:
        want = set(names)
        self.assertTrue(
            self._wait_until(lambda: want <= {n for tup in self._ledger_names() for n in tup}),
            f"台账未在超时内含条目 {want}，现状: {self._ledger_names()}",
        )
        return kn._read_pending_ledger(self.root)

    def _wait_ledger_empty(self) -> bool:
        return self._wait_until(lambda: kn._read_pending_ledger(self.root) == [])

    def _wait_workers_done(self, mgr) -> bool:
        return self._wait_until(
            lambda: not any(w.is_alive() for w in mgr._workers.values())
        )


# ── 3.1 台账生命周期 ─────────────────────────────────────────────────


class TestLedgerLifecycle(DistillResumeTestBase):
    def test_dispatch_writes_pending_entry(self):
        """dispatch 后台账含条目（含 queued_at 时间戳）。"""
        spawn = _GateSpawn()
        mgr = DistillManager(spawn=spawn)
        r = mgr.dispatch(self.root, [N1])
        self.assertTrue(r["dispatched"])
        ledger = self._wait_ledger_contains(N1)
        self.assertEqual([tuple(b["names"]) for b in ledger], [(N1,)])
        self.assertTrue(ledger[0]["queued_at"], "条目缺 queued_at 时间戳")
        spawn.release.set()
        self.assertTrue(self._wait_ledger_empty() and self._wait_workers_done(mgr))

    def test_batch_success_removes_entry(self):
        """批次成功收尾（无变更口径）后台账条目消失。"""
        spawn = _GateSpawn()
        mgr = DistillManager(spawn=spawn)
        with mock.patch.object(kn, "validate_knowledge", lambda p: []):
            mgr.dispatch(self.root, [N1])
            self._wait_ledger_contains(N1)
            spawn.release.set()
            self.assertTrue(
                self._wait_ledger_empty(), "成功收尾后 pending 条目未移除"
            )
        self.assertTrue(self._wait_workers_done(mgr))

    def test_giveup_discard_confirmed_removes_entry(self):
        """run 非零退出 → _give_up 清理确认（_discard_output=True）后条目消失。"""
        spawn = _GateSpawn(returncode=1)
        mgr = DistillManager(spawn=spawn)
        mgr.dispatch(self.root, [N1])
        self._wait_ledger_contains(N1)
        spawn.release.set()
        self.assertTrue(
            self._wait_ledger_empty(), "放弃产出清理确认后 pending 条目未移除"
        )
        self.assertTrue(self._wait_workers_done(mgr))

    def test_commit_failure_keeps_entry(self):
        """校验通过但提交失败：条目保留 + todo 台账注明重启续跑接管。"""
        spawn = _GateSpawn()
        mgr = DistillManager(spawn=spawn)
        with mock.patch.object(kn, "validate_knowledge", lambda p: []), \
                mock.patch.object(kn, "_commit_output", lambda p, n, baseline=None: None):
            mgr.dispatch(self.root, [N1])
            self._wait_ledger_contains(N1)
            spawn.release.set()
            self.assertTrue(self._wait_workers_done(mgr), "worker 未在超时内收尾")
        # 提交失败滞留路径：条目保留（保持「未完成」状态交 R3 恢复/人工兜底）
        self.assertEqual(
            self._ledger_names(), [(N1,)], "提交失败滞留路径 pending 条目被误清"
        )
        todo = (self.root / ".fenix" / "todo.md").read_text(encoding="utf-8")
        self.assertIn("校验通过但自动提交失败", todo)
        self.assertIn("重启续跑接管", todo)

    def test_gate_rejected_paths_no_ledger(self):
        """门控拒绝（归档缺失/disabled/回填期排队）不写台账。"""
        mgr = DistillManager(spawn=_GateSpawn())
        with mock.patch.object(kn, "_in_pytest", lambda: False), \
                mock.patch.object(kn, "_MANAGER", mgr):
            r1 = kn.dispatch_distill(self.root, N_GONE)
            self.assertEqual(r1["reason"], "archive-dir-missing")
            r2 = kn.dispatch_distill(
                self.root, N1, config={"knowledge": {"enabled": False}}
            )
            self.assertEqual(r2["reason"], "disabled")
            with mock.patch.object(kn, "ledger_has_pending", lambda p: True), \
                    mock.patch.object(kn, "register_archive_pending", lambda p, n: True):
                r3 = kn.dispatch_distill(self.root, N1)
            self.assertEqual(r3["reason"], "backfill-queued")
        self.assertEqual(mgr.pending(self.root), 0)
        self.assertFalse(
            self.ledger_path.exists(), "门控拒绝路径写入了 pending 台账"
        )

    def test_merged_batch_removes_all_entries(self):
        """同项目积压两条被合并为一次 run：收尾后两条目一并消失（防漏清陈旧条目）。"""
        spawn = _GateSpawn()
        mgr = DistillManager(spawn=spawn)
        with mock.patch.object(kn, "validate_knowledge", lambda p: []):
            mgr.dispatch(self.root, [N1])
            self.assertTrue(
                self._wait_until(lambda: spawn.calls == 1), "首批 run 未启动"
            )
            # 首批在飞期间连续入队两条 → worker 下一轮整体摘下合并为一次 run
            mgr.dispatch(self.root, [N2])
            mgr.dispatch(self.root, [N3])
            self.assertEqual(
                sorted(self._ledger_names()), [(N1,), (N2,), (N3,)]
            )
            spawn.release.set()
            self.assertTrue(
                self._wait_ledger_empty(), "合并 run 收尾后未按并集清除全部条目"
            )
        self.assertTrue(self._wait_workers_done(mgr))
        # 合并证据：spawn 共 2 次（首批 [N1] + 合并批 [N2,N3]），非 3 次逐条跑
        self.assertEqual(spawn.calls, 2)
        self.assertIn(str(self.root / "spec" / "archive" / N2), spawn.prompts[1])
        self.assertIn(str(self.root / "spec" / "archive" / N3), spawn.prompts[1])


# ── 3.2 台账容错与并发 ───────────────────────────────────────────────


class TestLedgerRobustness(DistillResumeTestBase):
    def test_corrupt_ledger_failopen(self):
        """台账损坏/非法 JSON 按空表处理且派发不受阻（追加后恢复合法）。"""
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self.ledger_path.write_text("{not json!!", encoding="utf-8")
        spawn = _GateSpawn()
        mgr = DistillManager(spawn=spawn)
        with mock.patch.object(kn, "validate_knowledge", lambda p: []):
            r = mgr.dispatch(self.root, [N1])  # 派发不受阻
            self.assertTrue(r["dispatched"])
            ledger = self._wait_ledger_contains(N1)
            self.assertEqual([tuple(b["names"]) for b in ledger], [(N1,)])
            spawn.release.set()
            self.assertTrue(self._wait_ledger_empty())
        self.assertTrue(self._wait_workers_done(mgr))
        # 恢复入口对空表（含损坏清空后）返回 0、不误派
        self.assertEqual(mgr.recover_pending(self.root), 0)

    def test_atomic_write_no_loss_interleaved(self):
        """原子回写并发入队不丢条目：多归档批量 + 交错单条，条目一条不少。"""
        spawn = _GateSpawn()
        mgr = DistillManager(spawn=spawn)
        with mock.patch.object(kn, "_in_pytest", lambda: False), \
                mock.patch.object(kn, "_MANAGER", mgr), \
                mock.patch.object(kn, "validate_knowledge", lambda p: []):
            r1 = kn.dispatch_distill_batch(self.root, [N1, N2, N3])
            self.assertTrue(r1["dispatched"])
            r2 = kn.dispatch_distill(self.root, N4)
            self.assertTrue(r2["dispatched"])
            ledger = self._wait_ledger_contains(N1, N2, N3, N4)
        self.assertEqual(
            sorted(tuple(b["names"]) for b in ledger),
            [(N1, N2, N3), (N4,)],
            "并发入队丢条目（同批多归档应合并为一条）",
        )
        spawn.release.set()
        self.assertTrue(self._wait_ledger_empty() and self._wait_workers_done(mgr))


# ── 3.3 恢复路径 ─────────────────────────────────────────────────────


class TestRecoverPending(DistillResumeTestBase):
    def _seed_ledger(self, entries):
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        kn._write_pending_ledger(self.root, entries)

    def test_recover_empty_or_missing_ledger(self):
        """无台账/空台账返回 0，不创建台账文件。"""
        mgr = DistillManager(spawn=_GateSpawn())
        self.assertEqual(mgr.recover_pending(self.root), 0)
        self.assertFalse(self.ledger_path.exists())

    def test_recover_redispatches_and_commits(self):
        """先清空后重派：放行条目重新落盘 → worker 消费完成入库提交 → 条目消失。"""
        self._seed_ledger([{"names": [N1], "queued_at": TS}])
        # fake spawn 写一个产出文件（走真实 git add/commit 落库）
        notes = self.root / "spec" / "knowledge" / "notes.md"

        def _write_output(prompt):
            notes.write_text("# 续跑产出\n", encoding="utf-8")

        spawn = _GateSpawn(on_prompt=_write_output)
        mgr = DistillManager(spawn=spawn)
        with mock.patch.object(kn, "_MANAGER", mgr), \
                mock.patch.object(kn, "validate_knowledge", lambda p: []):
            with self.assertLogs("fenixd.knowledge", level="INFO") as cm:
                n = mgr.recover_pending(self.root)
            self.assertEqual(n, 1)
            self.assertTrue(
                any("恢复重派（1 批" in o for o in cm.output),
                f"恢复日志缺失: {cm.output}",
            )
            # 先清空后重派：放行条目由 dispatch 写点立即重新落盘（非残留旧文）
            ledger = self._wait_ledger_contains(N1)
            self.assertEqual([tuple(b["names"]) for b in ledger], [(N1,)])
            # 放行首个 run → worker 消费完成入库提交，台账条目消失
            spawn.release.set()
            self.assertTrue(self._wait_ledger_empty(), "恢复批次完成后条目未移除")
        self.assertTrue(self._wait_workers_done(mgr))
        subject = _git(self.root, "log", "-1", "--format=%s").stdout.strip()
        self.assertEqual(subject, f"[fenix] knowledge: distill {N1}")

    def test_recover_gate_rejected_not_revived(self):
        """混合条目：归档目录缺失者按门控拒绝不复活，放行者重新落盘。"""
        self._seed_ledger([
            {"names": [N_GONE], "queued_at": TS},
            {"names": [N1], "queued_at": TS},
        ])
        spawn = _GateSpawn()
        mgr = DistillManager(spawn=spawn)
        with mock.patch.object(kn, "_MANAGER", mgr), \
                mock.patch.object(kn, "validate_knowledge", lambda p: []):
            with self.assertLogs("fenixd.knowledge", level="INFO") as cm:
                n = mgr.recover_pending(self.root)
            self.assertEqual(n, 1)
            self.assertTrue(any("恢复跳过" in o for o in cm.output), cm.output)
            ledger = self._wait_ledger_contains(N1)
            self.assertEqual(
                [tuple(b["names"]) for b in ledger],
                [(N1,)],
                "门控拒绝条目被复活（应随清空消失）",
            )
            spawn.release.set()
            self.assertTrue(self._wait_ledger_empty())
        self.assertTrue(self._wait_workers_done(mgr))


# ── 3.4 _is_idle 蒸馏维度 ────────────────────────────────────────────


class TestIdleDistillDimension(DistillResumeTestBase):
    def _daemon(self):
        """构造「尚未 initialize」的 FenixDaemon 裸对象（对齐
        tests/test_stale_code_selfheal.py::_DaemonParts 注入口径）。"""
        import fenixd as fenixd_mod

        daemon = fenixd_mod.FenixDaemon.__new__(fenixd_mod.FenixDaemon)
        daemon.config = {}
        daemon.logger = mock.MagicMock()
        daemon.pm_engine = mock.MagicMock()
        daemon.pm_engine._active_runs = 0
        daemon._admin_executor = None
        daemon._admin_pool_lock = threading.Lock()
        daemon._admin_pool_stats = {"submitted": 0, "completed": 0, "failed": 0}
        return daemon

    def test_worker_in_flight_not_idle(self):
        """worker 线程存活 → 非空闲；消费完恢复空闲。"""
        daemon = self._daemon()
        self.assertTrue(daemon._is_idle(), "基线应判空闲")
        spawn = _GateSpawn()
        mgr = DistillManager(spawn=spawn)
        with mock.patch.object(kn, "_MANAGER", mgr):
            mgr.dispatch(self.root, [N1])
            self.assertTrue(self._wait_until(lambda: spawn.calls == 1))
            self.assertFalse(daemon._is_idle(), "蒸馏 worker 在飞时 _is_idle 应为 False")
            spawn.release.set()
            self.assertTrue(self._wait_workers_done(mgr))
        self.assertTrue(daemon._is_idle(), "蒸馏消费完后应恢复空闲判定")

    def test_queue_nonempty_not_idle(self):
        """进程内队列非空（worker 未起的窗口）→ 非空闲。"""
        daemon = self._daemon()
        mgr = DistillManager(spawn=_GateSpawn())
        mgr._queues[str(self.root.resolve())] = [N1]
        with mock.patch.object(kn, "_MANAGER", mgr):
            self.assertFalse(daemon._is_idle(), "蒸馏队列非空时 _is_idle 应为 False")

    def test_dead_ledger_still_idle(self):
        """死台账不钉住自愈：台账文件在场但进程内无活体 → 空闲。"""
        daemon = self._daemon()
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        kn._write_pending_ledger(self.root, [{"names": [N1], "queued_at": TS}])
        self.assertTrue(
            daemon._is_idle(), "死台账（无 worker/队列）不应判非空闲"
        )

    def test_stub_missing_attrs_idle(self):
        """DistillManager 替身缺属性：按空闲且不抛异常。"""
        daemon = self._daemon()

        class _BareMgr:  # 无 _workers/_queues
            pass

        with mock.patch.object(kn, "_MANAGER", _BareMgr()):
            self.assertTrue(daemon._is_idle(), "替身缺属性应按空闲")

    def test_internal_error_non_idle(self):
        """内部状态不可读（非 AttributeError 异常注入）→ 按非空闲（宁紧勿松）。"""
        daemon = self._daemon()

        class _BrokenMgr:
            @property
            def _workers(self):
                raise RuntimeError("内部状态不可读")

        with mock.patch.object(kn, "_MANAGER", _BrokenMgr()):
            self.assertFalse(daemon._is_idle(), "内部状态不可读应按非空闲")

    def test_dispatcher_access_error_idle(self):
        """蒸馏管理器访问入口本身异常 → 按空闲（无法判定不钉自愈）。"""
        daemon = self._daemon()
        with mock.patch.object(kn, "_get_dispatcher", side_effect=RuntimeError("boom")):
            self.assertTrue(daemon._is_idle())


if __name__ == "__main__":
    unittest.main()
