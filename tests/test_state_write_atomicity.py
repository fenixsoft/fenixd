"""fix-state-atomicity-and-selfheal-restart 4.1 — STATE.md 写入原子性契约测试。

对应 spec/changes/fix-state-atomicity-and-selfheal-restart/specs/state-write-atomicity/spec.md：

- Requirement「STATE.md 写入的原子性（无丢失更新）」
  - Scenario 并发更新不同字段均保留
  - Scenario 跨进程并发写入不丢失更新（两个 StateMachine 实例 = 独立写入者）
  - Scenario 评审派发写入的 reviewer_run 不被并发覆盖
  - Scenario STATE.md 写入必留痕
- Requirement「冻结 error 的可靠持久化」
  - Scenario 冻结后并发写入不清除 error
  - Scenario 解冻恢复原状态而非回退 ready

**确定性交错铺路（design D4）**：`read_all` 被包一层「读后汇合屏障」，逼迫两个
写者都先各自拿到快照、再各自回写——这正是「丢失更新」的成因时序。修复后
（read-modify-write 收进同一把 flock）第二个写者被挡在锁外、屏障超时放行，
两者不可能基于同一陈旧快照回写，用例即通过。故每个并发用例在**未修补实现上
必然失败**（屏障保证交错），在修补后必然通过（锁保证串行），不依赖运气。
"""

import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_machine import (  # noqa: E402
    FROZEN_FIELD,
    StateMachine,
    parse_orig_status,
)
from core.state_machine import _NullLogger  # noqa: E402

FROZEN_ERROR = "用户指令冻结：原状态 reviewing · 人工介入"
RACE_BARRIER_TIMEOUT = 1.0


def _run_race(ops, timeout=RACE_BARRIER_TIMEOUT):
    """并发执行各 op（无参可调用），并在每个 `read_all` 之后插汇合屏障。

    两个写者都必须在屏障处汇合后才继续写入——旧实现（读/写分处锁外）下这必然
    造成「同快照回写」，新实现下第二个写者被 flock 阻塞、屏障超时放行。
    """
    barrier = threading.Barrier(len(ops), timeout=timeout)
    original_read_all = StateMachine.read_all

    def _barriered_read_all(self):
        specs = original_read_all(self)
        try:
            barrier.wait()
        except threading.BrokenBarrierError:
            # 对端被 flock 挡在锁外（或对端已超时放行）：串行已成立，直接继续
            pass
        return specs

    failures = []

    def _runner(fn):
        def _run():
            try:
                fn()
            except Exception as e:  # noqa: BLE001 — 收集后统一断言，避免线程内静默
                failures.append(f"{type(e).__name__}: {e}")

        return _run

    with mock.patch.object(StateMachine, "read_all", _barriered_read_all):
        threads = [threading.Thread(target=_runner(fn)) for fn in ops]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
    alive = [t for t in threads if t.is_alive()]
    assert not alive, f"并发写线程未在超时内收工: {len(alive)} 个"
    assert not failures, f"并发写线程异常: {failures}"


class _AtomicityBase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        self.state_path = self.root / ".fenix" / "STATE.md"
        self.logger = mock.MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        self.sm.add_spec(
            "demo",
            {
                "status": "reviewing",
                "priority": 5,
                "branch": None,
                "error": None,
                "reviewer_run": None,
            },
        )

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _peer(self):
        """第二个 StateMachine 实例（模拟 dashboard 独立进程的写入者）。"""
        return StateMachine(self.state_path, mock.MagicMock())


class TestConcurrentWriteNoLostUpdate(_AtomicityBase):
    def test_concurrent_updates_keep_both_fields(self):
        """并发更新不同字段：两字段改动均保留（旧实现丢其一）。"""
        peer = self._peer()
        _run_race(
            [
                lambda: self.sm.update_spec("demo", {"reviewer_run": "spec-review-demo-1"}),
                lambda: peer.update_spec("demo", {"branch": "fenix/demo"}),
            ]
        )
        entry = self.sm.read_one("demo")
        assert entry["reviewer_run"] == "spec-review-demo-1", "reviewer_run 被并发覆盖"
        assert entry["branch"] == "fenix/demo", "branch 被并发覆盖"

    def test_review_dispatch_write_not_clobbered_by_peer(self):
        """评审派发的 reviewer_run 不被并发写覆盖回 null（事故直接复现）。

        真实事故：解冻后 daemon 并发派发多个评审 run，某 spec 的 reviewer_run
        被更早快照覆盖回 null → consume_review_result 早退、spec 永停 reviewing。
        """
        peer = self._peer()
        _run_race(
            [
                lambda: self.sm.update_spec("demo", {"reviewer_run": "spec-review-demo-9"}),
                lambda: peer.update_spec("demo", {"error": None, "status": "reviewing"}),
            ]
        )
        entry = self.sm.read_one("demo")
        assert entry["reviewer_run"] == "spec-review-demo-9"

    def test_concurrent_add_spec_keeps_both_entries(self):
        """并发 add_spec：两条注册均保留（查重与插入须在同一锁内）。"""
        peer = self._peer()
        _run_race(
            [
                lambda: self.sm.add_spec("alpha", {}),
                lambda: peer.add_spec("beta", {}),
            ]
        )
        names = self.sm.read_all()
        assert "alpha" in names and "beta" in names, (
            f"并发 add_spec 丢失条目: {sorted(names)}"
        )

    def test_concurrent_remove_spec_removes_both(self):
        """并发 remove_spec：两条剔除均生效（不同源收敛则后写者复活先删者）。"""
        self.sm.add_spec("gamma", {})
        self.sm.add_spec("delta", {})
        peer = self._peer()
        _run_race(
            [
                lambda: self.sm.remove_spec("gamma"),
                lambda: peer.remove_spec("delta"),
            ]
        )
        names = self.sm.read_all()
        assert "gamma" not in names, "被并发写者以陈旧快照复活"
        assert "delta" not in names, "被并发写者以陈旧快照复活"


class TestFrozenErrorPersistence(_AtomicityBase):
    def test_frozen_error_survives_concurrent_write(self):
        """冻结 error 在并发写入后仍可读，parse_orig_status 返回原状态。"""
        peer = self._peer()
        _run_race(
            [
                lambda: self.sm.update_spec(
                    "demo", {"status": "blocked", FROZEN_FIELD: True, "error": FROZEN_ERROR}
                ),
                lambda: peer.update_spec("demo", {"reviewer_run": "spec-review-demo-2"}),
            ]
        )
        entry = self.sm.read_one("demo")
        assert parse_orig_status(entry.get("error")) == "reviewing", (
            "冻结 error 被并发写清除（原状态解析退化为 ready）"
        )
        assert entry["reviewer_run"] == "spec-review-demo-2"

    def test_unfreeze_restores_orig_status(self):
        """解冻（未显式指定 status）恢复原状态 reviewing，MUST NOT 回退 ready。"""
        assert self.sm.update_spec(
            "demo", {"status": "blocked", FROZEN_FIELD: True, "error": FROZEN_ERROR}
        )
        entry = self.sm.read_one("demo")
        orig = parse_orig_status(entry.get("error"))
        assert orig == "reviewing"
        assert self.sm.unfreeze_spec("demo", status=orig) is True
        after = self.sm.read_one("demo")
        assert after["status"] == "reviewing"
        assert after.get("error") is None

    def test_frozen_status_stripped_inside_lock(self):
        """冻结剥离判定基于锁内最新条目：并发冻结期间到达的自动 status 写不得放行。"""
        self.sm.update_spec("demo", {"status": "blocked", FROZEN_FIELD: True, "error": FROZEN_ERROR})
        self.sm.update_spec("demo", {"status": "ready"})  # 自动链路回写
        entry = self.sm.read_one("demo")
        assert entry["status"] == "blocked", "冻结保护失效"
        warns = " ".join(str(c) for c in self.logger.warning.call_args_list)
        assert "stripped" in warns


class TestWriteTraceability(_AtomicityBase):
    def test_update_spec_logs_spec_name_and_changed_fields(self):
        """写入必留痕：日志含 spec 名与本次所改字段键。"""
        self.sm.update_spec("demo", {"reviewer_run": "spec-review-demo-3"})
        infos = self.sm.logger.info.call_args_list
        matched = [
            c
            for c in infos
            if c.args[:2] == ("state_machine", "Updated SPEC 'demo'")
        ]
        assert matched, f"未产生写入留痕: {infos}"
        context = matched[-1].args[2] if len(matched[-1].args) > 2 else {}
        assert "reviewer_run" in context.get("updates", {})

    def test_project_state_logger_is_real_and_writes_log_file(self):
        """跨进程构造点注入的 logger 为真实落盘日志器（非 _NullLogger 静默兜底）。"""
        import logging

        from core.state_machine import project_state_logger

        std = logging.getLogger("fenixd")
        saved_handlers = list(std.handlers)
        try:
            logger = project_state_logger(self.root)
            assert logger is not None
            assert not isinstance(logger, _NullLogger)
            sm = StateMachine(self.state_path, logger)
            sm.update_spec("demo", {"reviewer_run": "spec-review-demo-4"})
            log_file = self.root / ".fenix" / "logs" / "fenixd.log"
            assert log_file.exists(), "真实 logger 未落盘"
            content = log_file.read_text(encoding="utf-8")
            assert "Updated SPEC 'demo'" in content
        finally:
            # 复原全局 "fenixd" 日志器 handler（core.logger.Logger 构造会重绑它，
            # 不还原会污染同进程后续用例的日志断言）
            for h in list(std.handlers):
                h.close()
                std.removeHandler(h)
            for h in saved_handlers:
                std.addHandler(h)


class TestCrossProcessLock(_AtomicityBase):
    """Scenario 跨进程并发写入不丢失更新：锁 MUST 是跨进程文件锁（flock）。"""

    def test_cross_process_writer_blocks_on_file_lock(self):
        """另一进程（独立解释器）的写入被进程持有的 flock 挡下，且释放后不覆盖先写。

        以真实子进程取证「锁是文件级的」：父进程先写 `reviewer_run` 并持有
        `.STATE.md.lock`，子进程（模拟 dashboard 独立进程）调 update_spec 必须
        阻塞；释放后子进程写入 `branch`，父进程已提交的 `reviewer_run` MUST 仍在
        （子进程读到的是包含父写入的最新态，而非其启动前的陈旧快照）。
        """
        import fcntl
        import subprocess

        assert self.sm.update_spec("demo", {"reviewer_run": "spec-review-parent"})
        lock_path = self.state_path.parent / ".STATE.md.lock"
        repo_root = Path(__file__).resolve().parent.parent
        child = (
            "import sys;"
            f"sys.path.insert(0, {str(repo_root)!r});"
            "from pathlib import Path;"
            "from core.state_machine import StateMachine;"
            f"StateMachine(Path({str(self.state_path)!r}), None)"
            ".update_spec('demo', {'branch': 'fenix/child'})"
        )
        with open(lock_path, "w") as lock_f:
            fcntl.flock(lock_f, fcntl.LOCK_EX)
            proc = subprocess.Popen(
                [sys.executable, "-c", child],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                proc.wait(timeout=1.0)
                blocked = False
            except subprocess.TimeoutExpired:
                blocked = True
        out, err = proc.communicate(timeout=30)
        assert blocked, f"子进程未在 flock 上阻塞（非跨进程锁）: {err!r}"
        assert proc.returncode == 0, f"子进程写入失败: {err!r}"
        assert out == b""
        entry = self.sm.read_one("demo")
        assert entry["branch"] == "fenix/child"
        assert entry["reviewer_run"] == "spec-review-parent", "跨进程写入覆盖了先写字段"


if __name__ == "__main__":
    unittest.main()
