"""端到端回归：三类在飞工作跨 restart_request 规划性重启存活
（spec-planned-restart-drain-effectiveness「端到端回归钉住」）。

以替身进程驱动**真实 shutdown 路径**（planned-restart-drain 3.1）：

- 在飞 evo 分析 run / implementer run：真实子进程按 ``_run_agent`` 同形态
  登记进 ``AgentRunner._running_agents``（run_id → Popen）；
- ocr 车道：真实 ``run_impl_ocr`` 在后台线程在飞，审查子进程为伪造
  ``bin/ocr_review.py`` 替身（端到端先例同 test_impl_ocr_parallel_lane）；
- daemon 为真实 FenixDaemon（patch PROJECT_ROOT/PRESERVE_SIDECAR/sys.exit，
  先例同 test_interrupt_recovery_preserve.make_daemon），agent_runner 为真实
  AgentRunner（``__new__`` 绕过 __init__）——车道登记/排水窗口豁免/checkpoint
  广播/超窗有序终止全走真实实现。

不挂真实 LLM：run 替身为 ``python -c sleep``，ocr 替身脚本睡指定秒数后落
合法 JSON 报告。断言四件事：run_drain_max_seconds 窗口内三者均不被 SIGTERM、
超窗有序终止、checkpoint 旗标对在册 run 广播、ocr 车道有终态且 serving
worktree 不被无主回收（终态收尾自清理）。
"""

import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import fenixd
from core.agent_runner.maintenance_runs import run_impl_ocr
from core.agent_runner.runner import AgentRunner

from test_agent_runner import FakeLogger

SPEC = "e2e-drain"
BRANCH = f"fenix/{SPEC}"
_EPOCH = 1790000000
RUN_EVO = f"evo-{SPEC}-{_EPOCH}"  # evo 分析 run 替身（spec 解析不支持 evo 前缀，保全跳过）
RUN_IMPL = f"impl-{SPEC}-{_EPOCH}-a1"  # implementer run 替身

# 替身 ocr 脚本：睡 FENIX_TEST_OCR_SLEEP 秒后落合法 JSON 报告（comments 空
# → 车道 completed 零 findings；参数全量容忍 parse_known_args）。缺省睡 1s：
# 在飞窗口需可观测（登记态轮询），否则子进程瞬起瞬灭错过断言窗口。
FAKE_OCR_SCRIPT = """\\
import argparse, json, os, time

parser = argparse.ArgumentParser()
parser.add_argument("--from", dest="from_commit")
parser.add_argument("--to", dest="to_commit")
parser.add_argument("--concurrency")
parser.add_argument("--effort")
parser.add_argument("--format")
parser.add_argument("--output")
parser.add_argument("--exclude")
parser.add_argument("--background")
args, _ = parser.parse_known_args()
time.sleep(float(os.environ.get("FENIX_TEST_OCR_SLEEP", "1.0")))
with open(args.output, "w", encoding="utf-8") as f:
    json.dump({"comments": [], "summary": {"input_tokens": 10, "output_tokens": 5}}, f)
"""


# ── fixture 组装（真实 git 仓库 + 真实 runner + 真实 daemon） ────────────────


def _git(root: Path, *args, check=True):
    r = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, timeout=60
    )
    if check and r.returncode != 0:
        raise RuntimeError(f"git {args} failed: {r.stderr}")
    return r


def _init_repo(root: Path) -> tuple:
    """tmp git 仓库：main + 实现分支（分支 head 含替身 ocr 脚本，detached 检出可跑）。"""
    root.mkdir(parents=True, exist_ok=True)
    (root / ".fenix").mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@fenix.local")
    _git(root, "config", "user.name", "t")
    (root / "src").mkdir()
    (root / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "checkout", "-q", "-b", BRANCH)
    bin_dir = root / "bin"
    bin_dir.mkdir()
    (bin_dir / "ocr_review.py").write_text(FAKE_OCR_SCRIPT, encoding="utf-8")
    (root / "src" / "a.py").write_text("x = 2\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "impl")
    base = _git(root, "merge-base", "main", BRANCH).stdout.strip()
    head = _git(root, "rev-parse", BRANCH).stdout.strip()
    return base, head


def _real_runner(root: Path) -> AgentRunner:
    """真实 AgentRunner（``__new__`` 绕过 ``__init__``，先例同既有排水单测）。"""
    r = AgentRunner.__new__(AgentRunner)
    r.config = {}
    r.project_root = root
    r.logger = FakeLogger()
    r._running_agents = {}
    # 与 runner.__init__ 同形：wait_for_running_agents 停机写 interrupted 标记
    # 的临界区锁（缺失则 AttributeError 被静默吞掉、标记不落盘）。
    r._run_finalize_lock = threading.Lock()
    return r


class _FakeSM:
    def read_one(self, spec):
        return None


class _FakeWM:
    def __init__(self):
        self.cleanup_protected = None

    def find_worktree_path(self, branch):
        return None

    def find_worktree_by_spec(self, spec_name):
        return None

    def cleanup_orphans(self, protected=None):
        self.cleanup_protected = protected or set()


def _make_daemon(monkeypatch, root: Path, run_drain: float, runner) -> fenixd.FenixDaemon:
    """真实 FenixDaemon + 真实 AgentRunner（shutdown 路径全真实）。

    配置取本 SPEC 合入前的部署形态（admin.shutdown_drain_seconds: 0），窗口由
    agents.run_drain_max_seconds 提供——规划性重启豁免夹紧后排水必须生效。
    """
    (root / ".fenix" / "restart_request").write_text("1\n", encoding="utf-8")
    monkeypatch.setattr(fenixd, "PROJECT_ROOT", root)
    monkeypatch.setattr(
        fenixd, "PRESERVE_SIDECAR", root / ".fenix" / "interrupted_runs.json"
    )
    monkeypatch.setattr(
        fenixd.sys, "exit", lambda code=0: (_ for _ in ()).throw(SystemExit(code))
    )
    daemon = fenixd.FenixDaemon()
    daemon.config = {
        "admin": {"shutdown_drain_seconds": 0},
        "agents": {"run_drain_max_seconds": run_drain},
    }
    daemon.logger = FakeLogger()
    daemon.state_machine = _FakeSM()
    daemon.worktree_manager = _FakeWM()
    daemon.agent_runner = runner
    daemon.pm_engine = SimpleNamespace(shutting_down=False)
    daemon._admin_thread = None
    daemon._admin_executor = None
    daemon.event_bus = None
    return daemon


def _spawn_run(seconds: float) -> subprocess.Popen:
    """在飞 run 替身进程（sleep 型，SIGTERM 可终止且返回码可判别）。"""
    # start_new_session=True 才是 _run_agent 同形态（独立成组 pgid==pid）：
    # 替身与 pytest 同组时，超窗有序终止的 guard_killpg 自保护守卫按
    # 「目标组=调用者自身组」拒绝击杀，替身失真。
    return subprocess.Popen(
        [sys.executable, "-c", f"import time; time.sleep({seconds})"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _register_runs(runner, seconds: float) -> dict:
    """按 _run_agent 同形态登记 evo/implementer 两个在飞 run 替身。"""
    procs = {"evo": _spawn_run(seconds), "impl": _spawn_run(seconds)}
    runner._running_agents[RUN_EVO] = procs["evo"]
    runner._running_agents[RUN_IMPL] = procs["impl"]
    return procs


def _start_ocr_lane(runner, base: str, head: str) -> threading.Thread:
    """后台线程在飞真实 run_impl_ocr（替身审查子进程）。"""
    def _lane():
        run_impl_ocr(runner, SPEC, BRANCH, base, head)

    t = threading.Thread(target=_lane, daemon=True, name="e2e-ocr-lane")
    t.start()
    return t


def _wait_lane_registered(runner, timeout: float = 20.0) -> str:
    """等 ocr 车道子进程真实登记进排水集合（在飞证据）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        lanes = [k for k in runner.running_lane_ids() if k.startswith("impl-ocr-")]
        if lanes:
            return lanes[0]
        time.sleep(0.05)
    pytest.fail("ocr 车道子进程未在期限内登记进排水集合")


def _spy_drain_wait(runner) -> list:
    """包真实 drain_wait 记录排水窗口（保留真实排水语义）。"""
    seen = []
    real = runner.drain_wait

    def _spy(timeout, _real=real, _seen=seen):
        _seen.append(timeout)
        return _real(timeout)

    runner.drain_wait = _spy
    return seen


def _assert_checkpoint_flags(root: Path) -> None:
    """checkpoint 旗标对两个在册 run 广播（ocr 车道不在 run 注册表、无旗标）。"""
    for rid in (RUN_EVO, RUN_IMPL):
        flag = root / ".fenix" / "runs" / f"{rid}.checkpoint.json"
        assert flag.exists(), f"在飞 run {rid} 未收到 checkpoint 旗标"
        payload = json.loads(flag.read_text(encoding="utf-8"))
        assert payload["action"] == "checkpoint"


def _read_lane_artifact(root: Path) -> dict:
    artifact_file = root / ".fenix" / "verify-progress" / SPEC / "code-review.json"
    assert artifact_file.exists(), "ocr 车道产物缺失（无终态记录）"
    return json.loads(artifact_file.read_text(encoding="utf-8"))


def _assert_lane_terminal_state(root: Path, artifact: dict, want_status: str,
                                reason_fragment: str) -> None:
    """车道终态：产物状态/reason、run 转录末行 result、worktree 自清理不在册。"""
    assert artifact["status"] == want_status, artifact.get("reason")
    assert reason_fragment in artifact["reason"], artifact["reason"]
    run_file = root / ".fenix" / "runs" / f"{artifact['run_id']}.jsonl"
    assert run_file.exists(), "车道 run 转录缺失"
    last = json.loads(run_file.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert last["type"] == "result", "车道 run 转录末行非终态 result"
    wt = root / ".fenix" / "verify-serving" / f"ocr-{artifact['run_id']}"
    assert not wt.exists(), "serving worktree 未被车道终态收尾清理（无主回收形态）"
    registered = _git(root, "worktree", "list", "--porcelain").stdout
    assert f"ocr-{artifact['run_id']}" not in registered, "worktree 仍在 git 注册表中"


class TestPlannedRestartDrainE2E:
    def test_three_inflight_works_finish_naturally_within_window(
        self, monkeypatch, tmp_path
    ):
        """窗口内自然完成：shutdown=0 部署的规划性重启排水生效，三方不被 SIGTERM。"""
        root = tmp_path / "proj"
        base, head = _init_repo(root)
        runner = _real_runner(root)
        procs = _register_runs(runner, seconds=1.5)
        lane_t = _start_ocr_lane(runner, base, head)
        _wait_lane_registered(runner)
        daemon = _make_daemon(monkeypatch, root, run_drain=60, runner=runner)
        seen = _spy_drain_wait(runner)

        with pytest.raises(SystemExit):
            daemon.shutdown()
        lane_t.join(timeout=20)
        assert not lane_t.is_alive(), "ocr 车道线程未在期限内收尾"

        # 规划性豁免：窗口 = min(run_drain 60, supervisor SIGKILL 等待 60 − 余量 10)
        assert seen == [50.0], f"排水窗口取值异常: {seen}"
        _assert_checkpoint_flags(root)
        # 窗口内自然完成：返回码 0（被 SIGTERM 则为负）
        assert procs["evo"].poll() == 0, "evo run 替身被信号终止"
        assert procs["impl"].poll() == 0, "implementer run 替身被信号终止"
        # ocr 车道 completed 终态 + run 转录末行 result + worktree 自清理
        artifact = _read_lane_artifact(root)
        _assert_lane_terminal_state(root, artifact, "completed", "")

    def test_three_inflight_works_orderly_terminated_on_window_expiry(
        self, monkeypatch, tmp_path
    ):
        """超窗有序终止：run 走 terminate 收口、ocr 车道 SIGTERM 落终态不丢载体。"""
        root = tmp_path / "proj"
        base, head = _init_repo(root)
        runner = _real_runner(root)
        procs = _register_runs(runner, seconds=60)
        # 审查子进程远超窗口（先设 env 再起车道：替身脚本启动时读取）
        monkeypatch.setenv("FENIX_TEST_OCR_SLEEP", "60")
        lane_t = _start_ocr_lane(runner, base, head)
        _wait_lane_registered(runner)
        daemon = _make_daemon(monkeypatch, root, run_drain=2, runner=runner)
        seen = _spy_drain_wait(runner)

        with pytest.raises(SystemExit):
            daemon.shutdown()
        lane_t.join(timeout=30)
        assert not lane_t.is_alive(), "ocr 车道线程未在期限内收尾"

        # 窗口 = min(run_drain 2, 50)；到期仍有残留 → 有序终止
        assert seen == [2.0], f"排水窗口取值异常: {seen}"
        _assert_checkpoint_flags(root)
        assert procs["evo"].poll() is not None, "evo run 替身未被超窗终止"
        assert procs["impl"].poll() is not None, "implementer run 替身未被超窗终止"
        # 车道被信号终止（SIGTERM → 负返回码）仍落 unavailable 终态
        artifact = _read_lane_artifact(root)
        _assert_lane_terminal_state(
            root, artifact, "unavailable", "信号终止"
        )
