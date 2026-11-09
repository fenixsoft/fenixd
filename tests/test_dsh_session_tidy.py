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
import os
import stat
import textwrap
from unittest.mock import patch

import pytest

from core.config import ConfigLoader
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
    outcome = "archived"
    raise_on_submit: Exception | None = None

    def __init__(self, project_root, web_url, dsh_home="", logger=None, **kw):
        FakeSubmitter.calls.append(
            {"project_root": project_root, "web_url": web_url, "dsh_home": dsh_home})
        self.logger = logger

    def submit(self, session_id):
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
