"""add-killpg-self-guard：清场击杀自保护守卫（core.proc_utils.guard_killpg）行为与防漂移测试。

覆盖 SPEC 的全部 Scenario：

- 替身 pid=0 / 替身 pid=自身 pid 流入收口后的清场函数不团灭宿主；
- 直传型 pgid=0 / pgid=-1 被守卫拒绝且无信号发出；
- 真实独立组（Popen start_new_session=True）正常清场不变；
- 守卫拒绝留 WARNING（含调用点标识与目标 pgid）；
- 解析型（resolve=True）与组长直传型（resolve=False）对同一目标判定一致；
- grep 断言：core 下清场击杀语义的裸 ``os.killpg`` 零存在（探活调用点显式
  豁免清单核对），防未来新增清场点绕过守卫。

守卫拒绝路径不 mock ``os.killpg``（真实语义优先，与 2026-10-07 事故取证口径
一致）：SIGTERM 对自身组的误投递用可捕获的信号处理器金丝雀断言「信号未发
出」；SIGKILL 不可捕获，以「调用正常返回且宿主仍存活」为断言——守卫若失效，
该用例的失败形态就是 2026-10-07 的套件团灭事故本身。
"""

import logging
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from core.proc_utils import guard_killpg, kill_process_group

CORE_DIR = Path(__file__).resolve().parent.parent / "core"

# 守卫的 WARNING 通道（与实现同源）
_GUARD_LOGGER = "fenixd.proc_utils"

# 越界不可达 pid：Linux 64 位 pid_max 上限 4194304（=2**22，/proc/sys/kernel/
# pid_max 的值比最大 PID 大 1），与 test_codefix_digest_metrics 替身同口径。
UNREACHABLE_PID = 2**22


class _SigtermCanary:
    """SIGTERM 金丝雀：记录本进程是否收到 SIGTERM（守卫失效时的最小可判反证）。"""

    def __init__(self):
        self.fired = 0
        self._prev = None

    def _handler(self, signum, frame):  # pragma: no cover - 仅守卫失效时触发
        self.fired += 1

    def __enter__(self):
        self._prev = signal.signal(signal.SIGTERM, self._handler)
        return self

    def __exit__(self, *exc):
        signal.signal(signal.SIGTERM, self._prev)
        return False


class _ListHandler(logging.Handler):
    """收集守卫 logger 的日志记录（断言拒绝留 WARNING / 正常清场无 WARNING）。"""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def messages(self):
        return [r.getMessage() for r in self.records]


class _warning_capture:
    """临时挂 _ListHandler 到守卫 logger 的上下文管理器。"""

    def __init__(self):
        self.handler = _ListHandler()

    def __enter__(self):
        logging.getLogger(_GUARD_LOGGER).addHandler(self.handler)
        return self.handler

    def __exit__(self, *exc):
        logging.getLogger(_GUARD_LOGGER).removeHandler(self.handler)
        return False


class _FakeProc:
    """最小 Popen 替身：pid 可注入怪值，收尾方法全部 no-op 且 kill 可观测。"""

    def __init__(self, pid):
        self.pid = pid
        self.kill_called = False

    def poll(self):
        return None

    def kill(self):
        self.kill_called = True

    def wait(self, timeout=None):
        return 0

    def communicate(self, prompt=None, timeout=None):
        return "", ""


def _spawn_session_leader(argv, capture_stdout=False):
    """start_new_session=True 独立成组的真实子进程（组长存活，pgid==pid）。"""
    return subprocess.Popen(
        argv,
        stdout=subprocess.PIPE if capture_stdout else subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        start_new_session=True,
    )


def _wait_reaped(proc, timeout=5.0):
    """有界等待 SIGKILL 投递生效：killpg 返回到 waitpid 可收尸有微小窗口。"""
    deadline = time.monotonic() + timeout
    while proc.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    return proc.poll()


def _reap(proc):
    """收尾兜底：用例失败路径也不留孤儿（守卫放行路径的正常清场另有专测）。"""
    if proc.poll() is None:
        try:
            proc.kill()
        except OSError:
            pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


# ── 守卫单点：两个拒绝分支 ────────────────────────────────────────────


class TestGuardRejectBranches:
    def test_direct_form_nonpositive_pgid_rejected_no_signal(self):
        """直传型 pgid=0 / pgid=-1 拒绝发出且无信号（killpg(0) 折算等价 kill(0)）。"""
        with _SigtermCanary() as canary, _warning_capture() as log:
            assert (
                guard_killpg(0, signal.SIGTERM, caller="t.nonpos", resolve=False) is False
            )
            assert (
                guard_killpg(-1, signal.SIGTERM, caller="t.nonpos", resolve=False) is False
            )
        assert canary.fired == 0
        # pgid=0 数值上 != os.getpgid(0)，必须由 pgid<=0 分支单独拦下
        msgs = log.messages()
        assert len(msgs) == 2
        assert all("t.nonpos" in m for m in msgs)
        assert any("pgid=0" in m for m in msgs)
        assert any("pgid=-1" in m for m in msgs)

    def test_own_process_group_rejected_both_forms_no_signal(self):
        """解析型（成员 pid=自身）与直传型（pgid=自身组）同一比对口径拒绝。"""
        own_pgid = os.getpgid(0)
        with _SigtermCanary() as canary, _warning_capture() as log:
            assert (
                guard_killpg(os.getpid(), signal.SIGTERM, caller="t.resolve", resolve=True)
                is False
            )
            assert (
                guard_killpg(own_pgid, signal.SIGTERM, caller="t.direct", resolve=False)
                is False
            )
        assert canary.fired == 0
        msgs = log.messages()
        assert len(msgs) == 2
        assert all("t.resolve" in m or "t.direct" in m for m in msgs)
        # WARNING 含调用点标识与目标 pgid
        assert any(str(own_pgid) in m and "t.resolve" in m for m in msgs)
        assert any(str(own_pgid) in m and "t.direct" in m for m in msgs)

    def test_own_group_sigkill_rejected_host_survives(self):
        """SIGKILL 不可捕获：以「返回 False 且宿主仍存活」为断言。"""
        assert guard_killpg(0, signal.SIGKILL, caller="t.sigkill", resolve=False) is False
        assert (
            guard_killpg(os.getpid(), signal.SIGKILL, caller="t.sigkill", resolve=True)
            is False
        )
        os.kill(os.getpid(), 0)  # 宿主仍存活（若被团灭本行不可达）

    def test_resolve_form_esrch_silent_semantics_preserved(self):
        """解析失败（ESRCH）走既有静默语义：返回 False 且不留 WARNING。"""
        with _warning_capture() as log:
            assert (
                guard_killpg(-1, signal.SIGTERM, caller="t.esrch", resolve=True) is False
            )
            assert (
                guard_killpg(UNREACHABLE_PID, signal.SIGKILL, caller="t.esrch", resolve=True)
                is False
            )
        assert log.messages() == []


# ── Scenario: 替身 pid=0 / pid=自身 pid 不再团灭宿主 ─────────────────


class TestFakePidDoesNotKillHost:
    def test_fake_pid_zero_across_lanes(self):
        """pid=0 流入解析型与直传型收口点：宿主不收信号、按组不存在静默。"""
        from core.knowledge import _kill_process_group as knowledge_kill
        from core.regression import _kill_process_group as regression_kill
        from core.agent_runner.maintenance_runs import (
            _kill_ocr_process_group as ocr_kill,
        )

        procs = [_FakeProc(0), _FakeProc(0), _FakeProc(0)]
        with _SigtermCanary() as canary, _warning_capture() as log:
            knowledge_kill(procs[0])      # resolve 型收口点
            regression_kill(procs[1])     # resolve 型收口点（SIGTERM→探活→SIGKILL 序列）
            ocr_kill(procs[2])            # 直传型收口点
        assert canary.fired == 0
        os.kill(os.getpid(), 0)  # 宿主仍存活
        # 三条车道都留了 WARNING（含 caller 标识）
        msgs = log.messages()
        assert len(msgs) == 3
        callers = " ".join(msgs)
        assert "knowledge._kill_process_group" in callers
        assert "regression._kill_process_group" in callers
        assert "maintenance_runs._kill_ocr_process_group" in callers

    def test_fake_pid_self_pid_across_lanes(self):
        """pid=调用者自身 pid：解析型解析到自身组被拒，宿主不收信号。"""
        from core.knowledge import _kill_process_group as knowledge_kill
        from core.regression import _kill_process_group as regression_kill
        from core.verify_engine.cli_runner import CliRunner

        procs = [_FakeProc(os.getpid()), _FakeProc(os.getpid())]
        with _SigtermCanary() as canary:
            knowledge_kill(procs[0])
            regression_kill(procs[1])
            CliRunner._kill_process_group(_FakeProc(os.getpid()))
        assert canary.fired == 0
        os.kill(os.getpid(), 0)  # 宿主仍存活

    def test_guard_reject_does_not_fall_back_to_single_pid_kill(self):
        """守卫拒绝 MUST NOT 触发单 pid proc.kill 降级（os.kill(0) 同为自身组广播）。"""
        from core.knowledge import _kill_process_group as knowledge_kill

        proc = _FakeProc(0)
        knowledge_kill(proc)
        assert proc.kill_called is False

    def test_codefix_digest_metrics_fake_pid_is_unreachable_positive(self):
        """存量替身怪值已修正：正值越界 pid，直传语境下不可达且不会被守卫误放行为真投递。"""
        from tests.test_codefix_digest_metrics import _FakeProc

        proc = _FakeProc([])
        assert proc.pid > 0
        assert proc.pid >= UNREACHABLE_PID  # ≥ pid_max 上界，不可能有真实组
        # 直传型：守卫放行（正 pgid）但 killpg 落 ESRCH 静默，宿主无恙
        from core.agent_runner.maintenance_runs import (
            _kill_ocr_process_group as ocr_kill,
        )

        with _warning_capture() as log:
            ocr_kill(proc)
        assert log.messages() == []  # ESRCH 静默，非守卫拒绝
        os.kill(os.getpid(), 0)


# ── Scenario: 正常独立组清场行为不变 ─────────────────────────────────


class TestRealSessionGroupCleanupUnchanged:
    def test_kill_process_group_full_sequence_with_sigterm_ignoring_child(self):
        """忽略 SIGTERM 的真实独立组：SIGTERM → 宽限 → SIGKILL 补刀全序列不变、无 WARNING。"""
        proc = _spawn_session_leader(
            [
                sys.executable,
                "-c",
                "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN);"
                " print('ready', flush=True); time.sleep(60)",
            ],
            capture_stdout=True,
        )
        try:
            assert proc.stdout.readline().strip() == "ready"
            pgid = os.getpgid(proc.pid)
            assert pgid == proc.pid  # start_new_session：独立成组
            with _warning_capture() as log:
                # 子进程刻意忽略 SIGTERM，wait 必然耗满宽限；断言针对全序列
                # （SIGTERM→宽限→SIGKILL 补刀）而非宽限时长本身，缩窗不改变判定。
                kill_process_group(proc, term_grace=0.2)
            _wait_reaped(proc)
            assert proc.poll() is not None
            assert proc.returncode == -signal.SIGKILL  # SIGTERM 被忽略 → SIGKILL 补刀
            assert log.messages() == []  # 正常清场不留告警
            with pytest.raises(ProcessLookupError):
                os.killpg(pgid, 0)  # 组已全灭
        finally:
            _reap(proc)

    def test_regression_kill_process_group_real_group(self):
        """core.regression._kill_process_group 对真实独立组：SIGTERM 即退，探活后不补刀。"""
        from core.regression import _kill_process_group as regression_kill

        proc = _spawn_session_leader(["sleep", "30"])
        try:
            pgid = os.getpgid(proc.pid)
            with _warning_capture() as log:
                regression_kill(proc)
            _wait_reaped(proc)
            assert proc.poll() is not None
            assert log.messages() == []
            with pytest.raises(ProcessLookupError):
                os.killpg(pgid, 0)
        finally:
            _reap(proc)

    def test_maintenance_runs_ocr_kill_real_group_direct_form(self):
        """直传型收口点（maintenance_runs._kill_ocr_process_group）对真实独立组行为不变。"""
        from core.agent_runner.maintenance_runs import (
            _kill_ocr_process_group as ocr_kill,
        )

        proc = _spawn_session_leader(["sleep", "30"])
        try:
            pgid = os.getpgid(proc.pid)
            with _warning_capture() as log:
                ocr_kill(proc)
            _wait_reaped(proc)
            assert proc.poll() is not None
            assert log.messages() == []
            with pytest.raises(ProcessLookupError):
                os.killpg(pgid, 0)
        finally:
            _reap(proc)


# ── Scenario: 两种入参形态语义一致 ────────────────────────────────────


class TestFormConsistency:
    def test_same_target_same_verdict_reject(self):
        """同一目标（调用者自身组）：解析型与直传型判定一致（均拒绝）。"""
        own_pgid = os.getpgid(0)
        with _SigtermCanary() as canary:
            via_resolve = guard_killpg(
                os.getpid(), signal.SIGTERM, caller="t.form.resolve", resolve=True
            )
            via_direct = guard_killpg(
                own_pgid, signal.SIGTERM, caller="t.form.direct", resolve=False
            )
        assert via_resolve is False
        assert via_direct is False
        assert canary.fired == 0

    def test_same_target_same_verdict_allow_real_group(self):
        """同一目标（真实独立组）：解析型与直传型判定一致（均放行且组灭）。"""
        for resolve in (True, False):
            proc = _spawn_session_leader(["sleep", "30"])
            try:
                sent = guard_killpg(
                    proc.pid, signal.SIGTERM, caller="t.form.allow", resolve=resolve
                )
                assert sent is True
                assert proc.wait(timeout=5) == -signal.SIGTERM
            finally:
                _reap(proc)

    def test_resolve_false_is_the_direct_transmit_semantics(self):
        """resolve=False 不做成员解析：pid 恒等 pgid（组长直传/已解析 pgid 两用）。"""
        # 直传一个当前不存在但合法的 pgid：不解析、直接 killpg 落 ESRCH → False（静默）
        with _warning_capture() as log:
            assert (
                guard_killpg(UNREACHABLE_PID, signal.SIGKILL, caller="t.dt", resolve=False)
                is False
            )
        assert log.messages() == []


# ── Scenario: grep 断言——core 下清场击杀裸 os.killpg 零存在 ──────────

# 守卫模块自身是唯一直传 os.killpg 的执行点
_GUARD_MODULE = "core/proc_utils.py"

# 探活调用点显式豁免清单（killpg(_, 0) 只做存在性检查、不投递信号），
# 值＝该文件内探活调用点数量（漂移即须人工核对并同步本清单）。
# regression 车道的整组探活已并入 core.proc_utils.kill_process_group 单点
# （item b090579ac5a0），经 guard_killpg 信号 0 表达，不再有本文件探活点。
# adjudication_narrative 的同款探活亦已并入该单点（item 614e441bb97a，
# 薄适配器 kill_process_group(sigkill_only_if_group_alive=True) 形态），
# 本文件不再有探活点，故不列。
_PROBE_EXEMPT = {
    "core/serving_registry.py": 2,  # kill_process_group 组空判定（pgid 路径 + 孤儿组接管路径）
}

# 探活形态：第二实参为字面量 0
_PROBE_SHAPE = re.compile(r"os\.killpg\(\s*[^,()]+,\s*0\s*\)")


def _iter_core_python_files():
    for path in sorted(CORE_DIR.rglob("*.py")):
        yield path.relative_to(CORE_DIR.parent).as_posix(), path


# 实际调用形态（排除 docstring/注释里反引号包裹的 ``os.killpg(...)`` 提法）
_CALL_SHAPE = re.compile(r"(?<!`)os\.killpg\(")


def _killpg_lines():
    """产出 (rel, lineno, line)——core 下所有出现 os.killpg( 实际调用的代码行。"""
    for rel, path in _iter_core_python_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            if _CALL_SHAPE.search(line):
                yield rel, lineno, line


class TestNoBareKillpgEscapesGuard:
    def test_no_signal_bearing_killpg_outside_guard(self):
        """清场击杀语义的裸 os.killpg 必须零存在（守卫模块自身除外）。"""
        violations = []
        for rel, lineno, line in _killpg_lines():
            if rel == _GUARD_MODULE:
                continue
            if _PROBE_SHAPE.search(line) and _PROBE_EXEMPT.get(rel, 0) > 0:
                continue  # 探活形态且文件在豁免清单
            violations.append(f"{rel}:{lineno}: {line.strip()}")
        assert not violations, (
            "发现绕过 guard_killpg 的清场击杀（须收口到 core.proc_utils.guard_killpg，"
            "探活调用点须登记进 _PROBE_EXEMPT）：\n" + "\n".join(violations)
        )

    def test_probe_exempt_list_pinned(self):
        """豁免清单核对：探活调用点按文件锚定数量，防清单漂移。"""
        counts = {rel: 0 for rel in _PROBE_EXEMPT}
        unregistered = []
        for rel, lineno, line in _killpg_lines():
            if rel == _GUARD_MODULE:
                continue
            if _PROBE_SHAPE.search(line):
                if rel in counts:
                    counts[rel] += 1
                else:
                    unregistered.append(f"{rel}:{lineno}: {line.strip()}")
        assert counts == _PROBE_EXEMPT, f"探活数量漂移：{counts} != {_PROBE_EXEMPT}"
        assert not unregistered, f"新探活调用点须登记进 _PROBE_EXEMPT：{unregistered}"

    def test_guard_module_is_the_only_direct_killpg(self):
        """守卫模块内直传 os.killpg 恰好一处（guard_killpg 的执行跳）。"""
        guard_hits = [
            (lineno, line.strip())
            for rel, lineno, line in _killpg_lines()
            if rel == _GUARD_MODULE
        ]
        assert len(guard_hits) == 1, f"守卫模块内 os.killpg 执行点漂移：{guard_hits}"
