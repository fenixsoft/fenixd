"""dsh 会话归档投递器测试（add-dsh-session-title-archive 3.1，3.2 并入本文件）。

覆盖（task 3.1 单测清单）：
- helper 退出码三分类：0=成功/已归档幂等（含队列残留清理）、2=可重试入队、
  1=致命不入队
- 入队/重试：JSONL round-trip、backoff 到期事件驱动消费、尝试计数累加
- 放弃阈值：次数触顶（缺省 200 次面，测试用小值）与队龄超限（先到为准）
- 重启恢复：新投递器实例消费旧实例入队的到期条目（队列文件即持久化态）
- 子进程异常折叠（node 缺失 → 可重试同面）、投递永不抛异常
- helper 子进程 argv 契约（--url/--secret-file/--session-id/--timeout）
- （3.2）config 读取面：agent.dsh_web_url 缺省与非法 URL 启动校验、
  agent.dsh_session_tidy 开关缺省与归一

helper 以 stub shell 脚本替身（node_executable="sh"、helper_path=stub）：
退出码经环境变量注入、stdout 打单行 JSON detail——与真实 helper 的子进程
契约（退出码 + stdout 末行 JSON）同形，协议面本身已由 dsh-bundle 侧
session-tidy-helper.test.ts 覆盖，此处不重复。
"""

import json
from pathlib import Path
import os
import stat
import textwrap
from unittest.mock import patch

import pytest

from core.config import ConfigLoader
from core.agent_runner.maintenance_runs import run_arbiter
from tests.test_arbiter_lane import FakeRunner
from core.dsh_session_tidy import (
    DEFAULT_MAX_ATTEMPTS,
    DshSessionTidySubmitter,
    EXIT_FATAL,
    EXIT_OK,
    EXIT_RETRYABLE,
    QUEUE_FILENAME,
    default_helper_path,
    resolve_dsh_home,
)


# ── stub helper ─────────────────────────────────────────────────────────────

STUB_TEMPLATE = textwrap.dedent(
    """\
    #!/bin/sh
    # 测试 stub：退出码经 TIDY_STUB_EXIT 注入；stdout 打单行 JSON（detail
    # 含收到的 --session-id（第 6 实参），供透传断言）。
    echo "{\\"ok\\": false, \\"session_id\\": \\"$6\\", \\"outcome\\": \\"stub\\", \\"detail\\": \\"stub-detail-$6\\"}"
    exit "$TIDY_STUB_EXIT"
    """
)


@pytest.fixture()
def stub_helper(tmp_path):
    path = tmp_path / "stub-helper.sh"
    path.write_text(STUB_TEMPLATE, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


class FakeClock:
    """可控时钟：submit/drain 共用同一 now（并发 1 串行语义下的确定性推进）。"""

    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_submitter(tmp_path, stub_helper, clock, **overrides):
    params = {
        "project_root": tmp_path,
        "web_url": "http://127.0.0.1:3080",
        "dsh_home": str(tmp_path / "dsh-home"),
        "timeout_seconds": 10,
        "helper_path": stub_helper,
        "node_executable": "sh",
        "clock": clock,
    }
    params.update(overrides)
    return DshSessionTidySubmitter(**params)


def read_queue(tmp_path) -> list[dict]:
    path = tmp_path / ".fenix" / "dsh_session_tidy" / QUEUE_FILENAME
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def run_stub(submitter, monkeypatch, exit_code):
    monkeypatch.setenv("TIDY_STUB_EXIT", str(exit_code))


# ── 退出码三分类 ────────────────────────────────────────────────────────────

class TestExitClassification:
    def test_exit0_archived_无队列残留(self, tmp_path, stub_helper, monkeypatch):
        run_stub(None, monkeypatch, EXIT_OK)
        submitter = make_submitter(tmp_path, stub_helper, FakeClock())
        assert submitter.submit("s-ok") == "archived"
        assert read_queue(tmp_path) == []

    def test_exit2_retryable_入队持久化(self, tmp_path, stub_helper, monkeypatch):
        run_stub(None, monkeypatch, EXIT_RETRYABLE)
        submitter = make_submitter(tmp_path, stub_helper, FakeClock())
        assert submitter.submit("s-retry") == "queued"
        entries = read_queue(tmp_path)
        assert len(entries) == 1
        entry = entries[0]
        assert entry["session_id"] == "s-retry"
        assert entry["attempts"] == 1
        assert entry["last_exit"] == EXIT_RETRYABLE
        assert entry["next_attempt_at"] > entry["enqueued_at"]

    def test_exit1_fatal_不入队(self, tmp_path, stub_helper, monkeypatch):
        run_stub(None, monkeypatch, EXIT_FATAL)
        submitter = make_submitter(tmp_path, stub_helper, FakeClock())
        assert submitter.submit("s-fatal") == "fatal"
        assert read_queue(tmp_path) == []

    def test_幂等成功清理队列残留(self, tmp_path, stub_helper, monkeypatch):
        # 先以 exit2 入队 → 时钟推进到 backoff 到期 → stub 改 exit0：后续
        # submit 的抽干阶段消费该条目并按成功移除（「已归档」幂等分类）。
        run_stub(None, monkeypatch, EXIT_RETRYABLE)
        clock = FakeClock()
        submitter = make_submitter(tmp_path, stub_helper, clock)
        assert submitter.submit("s-idem") == "queued"
        clock.advance(3600)
        run_stub(None, monkeypatch, EXIT_OK)
        assert submitter.submit("s-other") == "archived"
        # 幂等条目已被抽干消费移除；s-other 成功不入队 → 队列清空。
        assert read_queue(tmp_path) == []


# ── helper 子进程契约 ───────────────────────────────────────────────────────

class TestHelperInvocation:
    def test_argv_契约与会话id透传(self, tmp_path, stub_helper, monkeypatch):
        captured = {}
        real_run = __import__("subprocess").run

        def spy_run(argv, **kwargs):
            captured["argv"] = list(argv)
            return real_run(argv, **kwargs)

        run_stub(None, monkeypatch, EXIT_OK)
        submitter = make_submitter(tmp_path, stub_helper, FakeClock())
        with patch("core.dsh_session_tidy.subprocess.run", side_effect=spy_run):
            submitter.submit("s-argv")
        argv = captured["argv"]
        assert argv[0] == "sh"
        assert argv[2:4] == ["--url", "http://127.0.0.1:3080"]
        assert argv[4:6] == ["--secret-file", str(tmp_path / "dsh-home" / ".credentials.yaml")]
        assert argv[6:8] == ["--session-id", "s-argv"]
        assert argv[8:10] == ["--timeout", "10"]

    def test_detail_取stdout末行JSON(self, tmp_path, stub_helper, monkeypatch):
        run_stub(None, monkeypatch, EXIT_RETRYABLE)
        submitter = make_submitter(tmp_path, stub_helper, FakeClock())
        submitter.submit("s-detail")
        entry = read_queue(tmp_path)[0]
        assert entry["last_detail"] == "stub-detail-s-detail"

    def test_node缺失折叠为可重试入队(self, tmp_path, stub_helper, monkeypatch):
        monkeypatch.delenv("TIDY_STUB_EXIT", raising=False)
        submitter = make_submitter(
            tmp_path, stub_helper, FakeClock(), node_executable="definitely-missing-binary-xyz")
        assert submitter.submit("s-nonode") == "queued"
        assert read_queue(tmp_path)[0]["last_exit"] == EXIT_RETRYABLE

    def test_投递永不抛异常(self, tmp_path, stub_helper, monkeypatch):
        run_stub(None, monkeypatch, EXIT_OK)
        submitter = make_submitter(tmp_path, stub_helper, FakeClock())
        with patch.object(submitter, "_invoke_helper", side_effect=RuntimeError("unexpected")):
            assert submitter.submit("s-boom") == "queued"  # 意外折叠入队兜底，不冒泡


# ── 重试/放弃/重启恢复 ──────────────────────────────────────────────────────

class TestRetryLifecycle:
    def test_backoff_序列指数封顶1h(self):
        # 直接构造最小实例断言序列（不依赖文件面）。
        clock = FakeClock()
        s = DshSessionTidySubmitter(
            project_root="/tmp/unused", web_url="http://x", clock=clock,
            helper_path="/tmp/unused-helper", node_executable="true")
        assert s._backoff_seconds(1) == 30
        assert s._backoff_seconds(2) == 60
        assert s._backoff_seconds(3) == 120
        assert s._backoff_seconds(9) == 3600
        assert s._backoff_seconds(50) == 3600

    def test_尝试累加与到期重试消费(self, tmp_path, stub_helper, monkeypatch):
        run_stub(None, monkeypatch, EXIT_RETRYABLE)
        clock = FakeClock()
        submitter = make_submitter(tmp_path, stub_helper, clock, max_attempts=5)
        assert submitter.submit("s-a") == "queued"
        clock.advance(60)  # 越过第 1 次 backoff（30s）
        assert submitter.submit("s-b") == "queued"  # 抽干 s-a：attempts 1→2
        entries = {e["session_id"]: e for e in read_queue(tmp_path)}
        assert entries["s-a"]["attempts"] == 2
        assert entries["s-a"]["next_attempt_at"] >= clock.now

    def test_放弃阈值_次数触顶先到为准(self, tmp_path, stub_helper, monkeypatch):
        run_stub(None, monkeypatch, EXIT_RETRYABLE)
        clock = FakeClock()
        submitter = make_submitter(tmp_path, stub_helper, clock, max_attempts=2)
        assert submitter.submit("s-cap") == "queued"  # attempts=1
        clock.advance(60)
        # 下一次 submit 抽干 s-cap（attempts 1→2 触顶 max_attempts=2）→ 放弃移除。
        assert submitter.submit("s-next") == "queued"
        remaining = [e["session_id"] for e in read_queue(tmp_path)]
        assert remaining == ["s-next"]

    def test_放弃阈值_队龄超限(self, tmp_path, stub_helper, monkeypatch):
        run_stub(None, monkeypatch, EXIT_RETRYABLE)
        clock = FakeClock()
        # 队龄阈值 86.4s（0.001 天）；2 次退避（30s+60s=90s）未触顶即先撞队龄。
        submitter = make_submitter(tmp_path, stub_helper, clock, max_attempts=5, max_age_days=0.001)
        assert submitter.submit("s-age") == "queued"
        clock.advance(60)
        assert submitter.submit("s-keep") == "queued"  # attempts→2，队龄 60s 未超
        clock.advance(60)
        assert submitter.submit("s-keep2") == "queued"  # s-age 队龄 120s ≥ 86.4s → 放弃
        remaining = [e["session_id"] for e in read_queue(tmp_path)]
        assert "s-age" not in remaining
        assert "s-keep" in remaining

    def test_重启恢复_新实例消费旧队列(self, tmp_path, stub_helper, monkeypatch):
        # 实例 A 入队（模拟 daemon 生命周期结束）→ 实例 B（同 project_root）
        # 在时钟推进后首次 submit 即恢复消费（daemon 重启不丢）。
        run_stub(None, monkeypatch, EXIT_RETRYABLE)
        clock = FakeClock()
        first = make_submitter(tmp_path, stub_helper, clock)
        assert first.submit("s-restart") == "queued"
        clock.advance(3600)
        run_stub(None, monkeypatch, EXIT_OK)
        second = make_submitter(tmp_path, stub_helper, clock)
        assert second.submit("s-fresh") == "archived"
        # s-restart 已被新实例抽干消费移除；s-fresh 成功不入队 → 队列清空。
        assert read_queue(tmp_path) == []

    def test_队列并发1_串行投递(self, tmp_path, stub_helper, monkeypatch):
        run_stub(None, monkeypatch, EXIT_RETRYABLE)
        submitter = make_submitter(tmp_path, stub_helper, FakeClock())
        assert submitter.submit("s-1") == "queued"
        assert submitter.submit("s-2") == "queued"
        entries = read_queue(tmp_path)
        assert [e["session_id"] for e in entries] == ["s-1", "s-2"]

    def test_损坏行跳过不阻断(self, tmp_path, stub_helper, monkeypatch):
        queue = tmp_path / ".fenix" / "dsh_session_tidy" / QUEUE_FILENAME
        queue.parent.mkdir(parents=True, exist_ok=True)
        good = json.dumps({"session_id": "s-good", "enqueued_at": 0.0, "attempts": 1,
                           "next_attempt_at": 0.0, "last_exit": 2, "last_detail": "x"})
        queue.write_text("{broken json\n" + good + "\n", encoding="utf-8")
        clock = FakeClock()
        run_stub(None, monkeypatch, EXIT_RETRYABLE)
        submitter = make_submitter(tmp_path, stub_helper, clock)
        assert submitter.submit("s-new") == "queued"  # 抽干阶段重试 s-good（坏行静默跳过），s-new 入队
        remaining = [e["session_id"] for e in read_queue(tmp_path)]
        assert remaining == ["s-good", "s-new"]

    def test_缺省放弃阈值常量(self):
        assert DEFAULT_MAX_ATTEMPTS == 200


# ── dsh home 解析 ───────────────────────────────────────────────────────────

class TestResolveDshHome:
    def test_显式配置优先(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DSH_HOME", "/tmp/env-should-lose")
        assert resolve_dsh_home(str(tmp_path)) == tmp_path

    def test_环境变量次之(self, monkeypatch):
        monkeypatch.setenv("DSH_HOME", "/tmp/env-dsh")
        assert resolve_dsh_home("") == __import__("pathlib").Path("/tmp/env-dsh")

    def test_缺省回退home点dsh(self, monkeypatch):
        monkeypatch.delenv("DSH_HOME", raising=False)
        assert resolve_dsh_home("") == __import__("pathlib").Path.home() / ".dsh"

    def test_default_helper_path_仓库布局(self):
        path = default_helper_path()
        assert path.name == "session-tidy-helper.mjs"
        assert path.parent.name == "dist"


# ── config 读取面（task 3.2，与 3.1 单测同文件沉淀）─────────────────────────

class TestConfigDshTidyKeys:
    def test_dsh_web_url_缺省3080(self):
        assert ConfigLoader.get_dsh_web_url({}) == "http://127.0.0.1:3080"

    def test_dsh_web_url_合法值透传归一(self):
        assert ConfigLoader.get_dsh_web_url({"agent": {"dsh_web_url": "http://10.0.0.5:3080/"}}) \
            == "http://10.0.0.5:3080"

    def test_dsh_web_url_非法值启动校验报错(self):
        for bad in ("not-a-url", "ftp://x:1", "http://", 123, "http://host/path", None):
            with pytest.raises(ValueError):
                ConfigLoader.get_dsh_web_url({"agent": {"dsh_web_url": bad}})

    def test_dsh_session_tidy_缺省true(self):
        assert ConfigLoader.get_dsh_session_tidy_enabled({}) is True

    def test_dsh_session_tidy_显式false(self):
        assert ConfigLoader.get_dsh_session_tidy_enabled({"agent": {"dsh_session_tidy": False}}) is False

    def test_dsh_session_tidy_非法值回退缺省true(self):
        assert ConfigLoader.get_dsh_session_tidy_enabled({"agent": {"dsh_session_tidy": "off"}}) is True


# ── runner 终态挂接（task 3.3，AgentRunner.__new__ 轻量替身）────────────────

from core.agent_runner.runner import AgentRunner


class RecordingLogger:
    """最小 logger 替身：记录 warning/info 调用（component, message）。"""

    def __init__(self):
        self.events = []

    def warning(self, component, message, context=None):
        self.events.append(("warning", component, message))

    def info(self, component, message, context=None):
        self.events.append(("info", component, message))


class FakeSubmitter:
    """DshSessionTidySubmitter 替身：记录实例化实参与 submit 结果。"""

    calls = []
    submitted: list = []
    outcome = "archived"
    raise_on_submit: Exception | None = None

    def __init__(self, project_root, web_url, dsh_home="", logger=None, **kw):
        FakeSubmitter.calls.append(
            {"project_root": project_root, "web_url": web_url, "dsh_home": dsh_home})
        self.logger = logger

    def submit(self, session_id):
        FakeSubmitter.submitted.append(session_id)
        if FakeSubmitter.raise_on_submit is not None:
            raise FakeSubmitter.raise_on_submit
        return FakeSubmitter.outcome


def make_runner(tmp_path, config=None, logger=None):
    runner = AgentRunner.__new__(AgentRunner)
    runner.config = config if config is not None else {}
    runner.project_root = tmp_path
    runner.logger = logger if logger is not None else RecordingLogger()
    return runner


@pytest.fixture()
def fake_submitter(monkeypatch):
    FakeSubmitter.calls = []
    FakeSubmitter.submitted = []
    FakeSubmitter.outcome = "archived"
    FakeSubmitter.raise_on_submit = None
    monkeypatch.setattr("core.dsh_session_tidy.DshSessionTidySubmitter", FakeSubmitter)
    return FakeSubmitter


class TestRunnerTerminalHook:
    def test_非dsh_harness零动作(self, tmp_path, fake_submitter):
        logger = RecordingLogger()
        runner = make_runner(tmp_path, config={}, logger=logger)
        runner._run_dsh_session_id = {"r1": "sess-1"}
        runner._dsh_session_tidy_on_terminal("r1")
        assert fake_submitter.calls == []  # 不构造、不调 helper
        assert logger.events == []  # 零动作零告警
        assert runner._run_dsh_session_id == {}  # 登记已摘（生命周期卫生）

    def test_从未spawn静默零动作(self, tmp_path, fake_submitter):
        logger = RecordingLogger()
        runner = make_runner(tmp_path, config={"agent": {"harness": "dsh"}}, logger=logger)
        runner._run_dsh_session_id = {}
        runner._dsh_session_tidy_on_terminal("never-spawned")
        assert fake_submitter.calls == []
        assert logger.events == []  # 提前终态（frozen/熔断等）不 WARN

    def test_缺session_id仅WARN不调helper(self, tmp_path, fake_submitter):
        logger = RecordingLogger()
        runner = make_runner(tmp_path, config={"agent": {"harness": "dsh"}}, logger=logger)
        runner._run_dsh_session_id = {"r1": None}  # session 事件缺失 → 值 None
        runner._dsh_session_tidy_on_terminal("r1")
        assert fake_submitter.calls == []
        assert len(logger.events) == 1
        level, component, message = logger.events[0]
        assert level == "warning" and component == "agent_runner"
        assert "未捕获 session_id" in message

    def test_开关关闭暂停投递不清队列(self, tmp_path, fake_submitter):
        logger = RecordingLogger()
        runner = make_runner(
            tmp_path,
            config={"agent": {"harness": "dsh", "dsh_session_tidy": False}},
            logger=logger,
        )
        runner._run_dsh_session_id = {"r1": "sess-1"}
        runner._dsh_session_tidy_on_terminal("r1")
        assert fake_submitter.calls == []
        assert logger.events == []

    def test_成功形态_投递归档不影响终态(self, tmp_path, fake_submitter):
        logger = RecordingLogger()
        runner = make_runner(tmp_path, config={"agent": {"harness": "dsh"}}, logger=logger)
        runner._run_dsh_session_id = {"r1": "sess-9"}
        fake_submitter.outcome = "archived"
        runner._dsh_session_tidy_on_terminal("r1")  # 不抛即不影响终态
        assert fake_submitter.calls[0]["web_url"] == "http://127.0.0.1:3080"
        assert fake_submitter.calls[0]["project_root"] == tmp_path

    def test_queued形态_入队留痕(self, tmp_path, fake_submitter):
        logger = RecordingLogger()
        runner = make_runner(tmp_path, config={"agent": {"harness": "dsh"}}, logger=logger)
        runner._run_dsh_session_id = {"r1": "sess-9"}
        fake_submitter.outcome = "queued"
        runner._dsh_session_tidy_on_terminal("r1")
        assert any(e[0] == "info" and "入队重试" in e[2] for e in logger.events)

    def test_submit异常形态_fail_open不影响终态(self, tmp_path, fake_submitter):
        # submitter 抛异常（超时/崩溃面）→ WARN 留痕，异常不外冒（终态指标
        # 与门禁照常——本方法外层 try/except 契约）。
        logger = RecordingLogger()
        runner = make_runner(tmp_path, config={"agent": {"harness": "dsh"}}, logger=logger)
        runner._run_dsh_session_id = {"r1": "sess-9"}
        fake_submitter.raise_on_submit = TimeoutError("helper hang")
        runner._dsh_session_tidy_on_terminal("r1")
        assert any(e[0] == "warning" and "归档投递异常" in e[2] for e in logger.events)

    def test_attempt后缀run_id归一消费(self, tmp_path, fake_submitter):
        # 登记键为 base run_id（_run_agent 内归一），挂钩以 attempt 后缀形态
        # 调用（_execute_agent finally 传原始 run_id）→ 归一后命中同一键。
        logger = RecordingLogger()
        runner = make_runner(tmp_path, config={"agent": {"harness": "dsh"}}, logger=logger)
        runner._run_dsh_session_id = {"spec-x-123": "sess-a"}
        runner._dsh_session_tidy_on_terminal("spec-x-123-a1-r1")
        assert fake_submitter.calls[0] is not None
        assert runner._run_dsh_session_id == {}

    def test_registry缺失形态_替身轻量上下文(self, tmp_path, fake_submitter):
        # AgentRunner.__new__ 直构替身无 _run_dsh_session_id 属性 → getattr
        # 回退 None → 静默零动作（对齐 _log_run_metrics 替身回退口径）。
        logger = RecordingLogger()
        runner = make_runner(tmp_path, config={"agent": {"harness": "dsh"}}, logger=logger)
        runner._dsh_session_tidy_on_terminal("r1")
        assert fake_submitter.calls == []
        assert logger.events == []

    def test_config异常形态_fail_open(self, tmp_path, fake_submitter, monkeypatch):
        # get_dsh_web_url 抛错（非法 URL 配置）→ 折进外层 except WARN，不外冒。
        logger = RecordingLogger()
        runner = make_runner(
            tmp_path,
            config={"agent": {"harness": "dsh", "dsh_web_url": "not-a-url"}},
            logger=logger,
        )
        runner._run_dsh_session_id = {"r1": "sess-9"}
        runner._dsh_session_tidy_on_terminal("r1")
        assert any(e[0] == "warning" and "归档投递异常" in e[2] for e in logger.events)

    def test_attempt链多次spawn全量归档(self, tmp_path, fake_submitter):
        # fix-dsh-tidy-attempt-sessions：同一 run 多次 attempt（-a1/-a2/-a3 重试）
        # 各 spawn 独立 dsh 会话，登记值为列表——终态须全量按序投递，而非只
        # 归档末次 attempt 的会话（此前纯赋值覆盖致前序会话堆积 web 未分组）。
        logger = RecordingLogger()
        runner = make_runner(tmp_path, config={"agent": {"harness": "dsh"}}, logger=logger)
        runner._run_dsh_session_id = {"r1": ["s-a1", "s-a2", "s-a3"]}
        runner._dsh_session_tidy_on_terminal("r1")  # 不抛即不影响终态
        assert fake_submitter.submitted == ["s-a1", "s-a2", "s-a3"]
        assert runner._run_dsh_session_id == {}  # 登记已摘（生命周期卫生）
        assert sum(1 for e in logger.events if e[0] == "info" and "已归档" in e[2]) == 3

    def test_登记值空列表视同未捕获(self, tmp_path, fake_submitter):
        # 防御面：空列表 = 无可归档目标，走既有「未捕获」WARN 面，不投递。
        logger = RecordingLogger()
        runner = make_runner(tmp_path, config={"agent": {"harness": "dsh"}}, logger=logger)
        runner._run_dsh_session_id = {"r1": []}
        runner._dsh_session_tidy_on_terminal("r1")
        assert fake_submitter.calls == []
        assert any(e[0] == "warning" and "未捕获 session_id" in e[2] for e in logger.events)


class TestDshSessionIdRegistration:
    """_register_dsh_session_id：逐 attempt 登记收口（fix-dsh-tidy-attempt-sessions）。

    此前 _run_agent 内联纯赋值 `registry[base] = session_id`——多次 attempt
    互相覆盖，终态只剩末次 attempt 的会话可归档。新契约：列表追加 + 同 id
    幂等 + None 哨兵语义保持（键在值 None = spawn 了但 session 事件缺失）。
    """

    def _runner(self, tmp_path):
        runner = AgentRunner.__new__(AgentRunner)
        runner.config = {"agent": {"harness": "dsh"}}
        runner.project_root = tmp_path
        runner.logger = RecordingLogger()
        return runner

    def test_首登成列表(self, tmp_path):
        runner = self._runner(tmp_path)
        runner._register_dsh_session_id("spec-x-1-a1", "s1")
        assert runner._run_dsh_session_id == {"spec-x-1": ["s1"]}

    def test_多attempt追加不覆盖(self, tmp_path):
        runner = self._runner(tmp_path)
        runner._register_dsh_session_id("spec-x-1-a1", "s1")
        runner._register_dsh_session_id("spec-x-1-a2", "s2")
        runner._register_dsh_session_id("spec-x-1-a3", "s3")
        assert runner._run_dsh_session_id == {"spec-x-1": ["s1", "s2", "s3"]}

    def test_同id幂等_resume重放不重复(self, tmp_path):
        runner = self._runner(tmp_path)
        runner._register_dsh_session_id("r1-a1", "s1")
        runner._register_dsh_session_id("r1-a1", "s1")
        assert runner._run_dsh_session_id == {"r1": ["s1"]}

    def test_none尝试不擦除既有捕获(self, tmp_path):
        # 某 attempt spawn 了但 session 事件缺失：既有 id 保留（仍可归档），
        # 不得翻成 None 哨兵抹掉前序捕获。
        runner = self._runner(tmp_path)
        runner._register_dsh_session_id("r1-a1", "s1")
        runner._register_dsh_session_id("r1-a2", None)
        assert runner._run_dsh_session_id == {"r1": ["s1"]}

    def test_首次none哨兵(self, tmp_path):
        # 首个 attempt 即未捕获：None 哨兵（消费侧 WARN 面，区别于键不在=
        # run 从未 spawn 的零动作）。
        runner = self._runner(tmp_path)
        runner._register_dsh_session_id("r1-a1", None)
        assert runner._run_dsh_session_id == {"r1": None}

    def test_none哨兵后捕获起列表(self, tmp_path):
        runner = self._runner(tmp_path)
        runner._register_dsh_session_id("r1-a1", None)
        runner._register_dsh_session_id("r1-a2", "s2")
        assert runner._run_dsh_session_id == {"r1": ["s2"]}

    def test_str旧形态防御(self, tmp_path):
        # 进程内存态遇旧 str 形态（跨版本防御）：并入列表不丢前序 id。
        runner = self._runner(tmp_path)
        runner._run_dsh_session_id = {"r1": "s0"}
        runner._register_dsh_session_id("r1-a2", "s2")
        assert runner._run_dsh_session_id == {"r1": ["s0", "s2"]}


class TestMaintenanceLaneTidyHooks:
    """admin/arbiter 直调车道终态 tidy 挂接契约（fix-dsh-tidy-maintenance-lanes）。

    根因（2026-11-09 未分组复查实证）：add-dsh-session-title-archive 3.3 的
    挂接只覆盖 _execute_agent finally（dispatch 族）与 dispute-judge/
    spec-review 直调 finally——run_administrator / run_arbiter（maintenance_
    runs.py 直调车道）漏挂，其 dsh 会话终态后永漏归档、堆积 web 未分组
    （当日 cloud-phone 未分组 9 条中 admin ×4 + arbiter ×2）。
    """

    def test_arbiter_成功终态投递(self, tmp_path):
        from tests.test_arbiter_guardrails import GOOD_REPORT

        class TidySpyRunner(FakeRunner):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                self.tidy_calls = []

            def _dsh_session_tidy_on_terminal(self, run_id):
                self.tidy_calls.append(run_id)

        runner = TidySpyRunner(tmp_path, script={"run": GOOD_REPORT})
        result = run_arbiter(runner, {"spec": "spec-a",
                                      "signal_type": "verify_env_blocked"})
        assert result["ok"] is True
        assert len(runner.tidy_calls) == 1
        assert runner.tidy_calls[0] == result["run_id"]

    def test_arbiter_异常终态仍投递(self, tmp_path):

        class TidySpyRunner(FakeRunner):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                self.tidy_calls = []

            def _dsh_session_tidy_on_terminal(self, run_id):
                self.tidy_calls.append(run_id)

        runner = TidySpyRunner(tmp_path, script={"run": "raise"})
        result = run_arbiter(runner, {"spec": "spec-a",
                                      "signal_type": "verify_env_blocked"})
        assert result["ok"] is False
        # 异常终态（gateway stall 等）同为终态外口：投递恰好一次
        assert len(runner.tidy_calls) == 1
        assert runner.tidy_calls[0] == result["run_id"]

    def test_admin_arbiter_挂接源码契约(self):
        # AST 源码契约（对齐 test_run_agent_call_site_arity.py 先例）：
        # admin 车道缺端到端测试基建，用源码扫描钉死两直调车道的挂接在位，
        # 任一侧回归漂移即红。
        import ast
        src = (Path(__file__).resolve().parent.parent
               / "core" / "agent_runner" / "maintenance_runs.py")
        tree = ast.parse(src.read_text(encoding="utf-8"))
        hooked = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if node.name not in ("run_administrator", "run_arbiter"):
                continue
            # 兼容两种在位形态：直调 runner._dsh_session_tidy_on_terminal(run_id)
            # （Attribute 调用）与 getattr 判空中间变量（字符串常量实参）。
            hooked[node.name] = any(
                (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "_dsh_session_tidy_on_terminal")
                or (isinstance(n, ast.Constant)
                    and n.value == "_dsh_session_tidy_on_terminal")
                for n in ast.walk(node))
        assert hooked.get("run_administrator") is True, (
            "run_administrator 缺 _dsh_session_tidy_on_terminal 终态挂接"
            "——admin 车道 dsh 会话将漏归档堆积 web 未分组")
        assert hooked.get("run_arbiter") is True, (
            "run_arbiter 缺 _dsh_session_tidy_on_terminal 终态挂接"
            "——arbiter 车道 dsh 会话将漏归档堆积 web 未分组")
