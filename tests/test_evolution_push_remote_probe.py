"""evo-fix-evolution-push-remote-probe-skip：回写 push 前探测与恒失败聚合。

覆盖 tasks 三条测试验收：
- 3.1 零 remote 仓回写：两车道（evolution ``_commit_todo_marker`` 与
  self_review ``_commit_todo``）各验证——push 被跳过（无 push 子进程调用）、
  DEBUG 日志含仓路径、无 WARNING、commit 仍产生；self_review 车道以注入
  logger／调用记录取证，不依赖 fenixd.log 中央 sink（兄弟仓场景该车道在
  中央 sink 静默，见 MERGE-NOTES 验证纪律）。
- 3.2 同仓连续两次 push 失败：全程仅一条 WARNING（首败聚合，文案含仓路径
  与连续失败计数），第二次失败仅递增计数且降级 DEBUG、无新 WARNING。
- 3.3 有 remote 但单次 push 失败：记常规 WARNING 且文案含仓路径与 stderr
  尾部（task 1.3 的验收）。

另有聚合语义边界钉：跨日重置当日已告警标记（连续计数不清零）、push 成功
清零连续计数（同日不新告警）、self_review 车道不聚合（design：每日至多一次
push 无刷屏面）。

取证方式：push 子进程调用经 monkeypatch 包装 ``subprocess.run`` 记录（委托
真实执行，git 行为全程真实）；日志经 caplog（evolution 车道 logger
``fenixd.evolution``）与注入 RecLogger（self_review 车道两参形态）取证。
"""
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import core.timelib as timelib_mod  # noqa: E402
from core.evolution import _commit_todo_marker, _push_aggr_state  # noqa: E402
from core.self_review import SelfReviewScheduler  # noqa: E402

LOGGER_NAME = "fenixd.evolution"


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=30
    )


def _tracked_repo(tmp_path, remote=None):
    """带 tracked ``.fenix/todo.md`` 初始提交的最小 git 仓库。

    ``remote`` 非空时配置 origin（调用方随后可 set-url 置为坏地址制造
    「有 remote 但 push 失败」场景）。
    """
    repo = tmp_path / "proj"
    (repo / ".fenix").mkdir(parents=True)
    (repo / ".fenix" / "todo.md").write_text(
        "## 2026-09-13\n\n### 浪费\n- **问题甲**\n", encoding="utf-8"
    )
    assert _git(repo, "init", "-q").returncode == 0
    _git(repo, "config", "user.name", "Fenix Test")
    _git(repo, "config", "user.email", "test@fenix.local")
    _git(repo, "add", "--", ".fenix/todo.md")
    _git(repo, "commit", "-q", "-m", "init")
    if remote is not None:
        _git(repo, "remote", "add", "origin", remote)
    return repo


def _repo_with_upstream(tmp_path):
    """带可用 origin（本地 bare 仓）且分支已设上游的仓库。

    生产链路裸 ``git push`` 依赖已设上游（push.default=simple 无上游直接
    报 upstream 错误，到不了远端接触阶段），故 setup 期先对真实 bare 仓
    ``push -u`` 成功一次；测试体再用 set-url 置为坏地址制造远端接触失败。
    """
    bare = tmp_path / "backup.git"
    assert _git(tmp_path, "init", "-q", "--bare", str(bare)).returncode == 0
    repo = _tracked_repo(tmp_path, remote=str(bare))
    assert _git(repo, "push", "-u", "origin", "HEAD").returncode == 0
    return repo, bare


def _break_remote(repo, tmp_path):
    """把 origin 置为不存在的路径：有 remote 配置但远端接触必败。"""
    broken = str(tmp_path / "nowhere.git")
    r = _git(repo, "remote", "set-url", "origin", broken)
    if r.returncode != 0:
        # 仓库尚未配置 origin：直接添加
        r = _git(repo, "remote", "add", "origin", broken)
    assert r.returncode == 0
    return broken


def _bump_todo(repo):
    """追加 todo.md 变更：无变更时提交链在「nothing to commit」分支提前
    返回，到不了 push，连续失败场景必须逐次制造新变更。"""
    todo = repo / ".fenix" / "todo.md"
    todo.write_text(
        todo.read_text(encoding="utf-8") + "\n- 追加标记\n", encoding="utf-8"
    )


def _todo_commit_count(repo):
    out = _git(repo, "rev-list", "--count", "HEAD", "--", ".fenix/todo.md").stdout
    out = out.strip()
    return int(out) if out.isdigit() else 0


def _track_push(monkeypatch):
    """包装 subprocess.run 记录 push 调用并委托真实执行，返回调用清单。"""
    calls = []
    real_run = subprocess.run

    def wrapper(cmd, *args, **kwargs):
        if isinstance(cmd, (list, tuple)) and "push" in cmd:
            calls.append(list(cmd))
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", wrapper)
    return calls


@pytest.fixture(autouse=True)
def _fresh_push_aggr_state():
    """聚合状态为进程内模块级：逐用例清零，避免跨用例计数串扰。"""
    _push_aggr_state.clear()
    yield
    _push_aggr_state.clear()


class RecLogger:
    """两参形态（component, message）记录 logger——self_review 车道取证用。"""

    def __init__(self):
        self.records = []

    def _rec(self, level, component, msg, *a, **k):
        self.records.append((level, component, str(msg)))

    def debug(self, component, msg, *a, **k):
        self._rec("DEBUG", component, msg, *a, **k)

    def info(self, component, msg, *a, **k):
        self._rec("INFO", component, msg, *a, **k)

    def warning(self, component, msg, *a, **k):
        self._rec("WARNING", component, msg, *a, **k)

    def error(self, component, msg, *a, **k):
        self._rec("ERROR", component, msg, *a, **k)

    def of_level(self, level):
        return [m for lvl, _, m in self.records if lvl == level]


class FakeSM:
    def read_all(self):
        return {}


def _make_scheduler(proot, logger):
    config = {
        "admin": {
            "self_review": {"enabled": True, "run_at": "22:00", "read_todo": False}
        }
    }
    return SelfReviewScheduler(config, proot, logger, FakeSM())


# ── 3.1 零 remote 仓回写：两车道跳过语义 ──────────────────────────


class TestZeroRemoteSkip:
    def test_evolution_lane_skips_push(self, tmp_path, monkeypatch, caplog):
        """零 remote：push 被跳过（无 push 子进程）、DEBUG 含仓路径、
        无 WARNING、commit 仍产生。"""
        repo = _tracked_repo(tmp_path)  # 不配置 remote
        _bump_todo(repo)
        push_calls = _track_push(monkeypatch)
        base = _todo_commit_count(repo)

        with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
            assert _commit_todo_marker(repo) is True

        assert push_calls == []
        assert _todo_commit_count(repo) == base + 1
        debug_msgs = [
            r.getMessage() for r in caplog.records if r.levelname == "DEBUG"
        ]
        assert any("零 remote" in m and str(repo) in m for m in debug_msgs)
        warnings = [
            r.getMessage() for r in caplog.records if r.levelname == "WARNING"
        ]
        assert warnings == []

    def test_self_review_lane_skips_push(self, tmp_path, monkeypatch):
        """零 remote（self_review 车道，注入 logger 取证）：同款跳过语义。"""
        repo = _tracked_repo(tmp_path)
        _bump_todo(repo)
        logger = RecLogger()
        sched = _make_scheduler(repo, logger)
        push_calls = _track_push(monkeypatch)
        base = _todo_commit_count(repo)

        assert sched._commit_todo("2026-10-30") is True

        assert push_calls == []
        assert _todo_commit_count(repo) == base + 1
        debugs = logger.of_level("DEBUG")
        assert any("零 remote" in m and str(repo) in m for m in debugs)
        assert logger.of_level("WARNING") == []


# ── 3.2 同仓连续两次 push 失败：聚合告警 ──────────────────────────


class TestConsecutiveFailureAggregation:
    def test_two_failures_single_warning(self, tmp_path, monkeypatch, caplog):
        """首败发聚合 WARNING（含仓路径与连续失败计数），次败仅递增计数
        降级 DEBUG、无新 WARNING。"""
        repo, _bare = _repo_with_upstream(tmp_path)
        _break_remote(repo, tmp_path)
        push_calls = _track_push(monkeypatch)

        with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
            _bump_todo(repo)
            assert _commit_todo_marker(repo) is True  # 首败
            _bump_todo(repo)
            assert _commit_todo_marker(repo) is True  # 次败

        # 两次都真实执行了 push 子进程（有 remote，探测不拦截）
        assert len(push_calls) == 2
        warnings = [
            r.getMessage() for r in caplog.records if r.levelname == "WARNING"
        ]
        assert len(warnings) == 1
        assert str(repo) in warnings[0]
        assert "连续第 1 次失败" in warnings[0]
        assert "nowhere.git" in warnings[0]  # stderr 尾部在文案内
        debug_msgs = [
            r.getMessage() for r in caplog.records if r.levelname == "DEBUG"
        ]
        assert any("连续失败计数 2" in m and str(repo) in m for m in debug_msgs)

    def test_alert_flag_resets_next_day_counter_kept(
        self, tmp_path, monkeypatch, caplog
    ):
        """跨日重置的是当日已告警标记，连续失败计数不清零：次日首败再发
        含最新计数的一条聚合。"""
        repo, _bare = _repo_with_upstream(tmp_path)
        _break_remote(repo, tmp_path)
        monkeypatch.setattr(timelib_mod, "now_local", lambda: datetime(2026, 10, 29, 23, 50))

        with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
            _bump_todo(repo)
            assert _commit_todo_marker(repo) is True  # day1 首败 WARNING 计数 1
            _bump_todo(repo)
            assert _commit_todo_marker(repo) is True  # day1 次败 DEBUG 计数 2

            monkeypatch.setattr(
                timelib_mod, "now_local", lambda: datetime(2026, 10, 30, 0, 10)
            )
            _bump_todo(repo)
            assert _commit_todo_marker(repo) is True  # day2 首败 WARNING 计数 3

        warnings = [
            r.getMessage() for r in caplog.records if r.levelname == "WARNING"
        ]
        assert len(warnings) == 2
        assert "连续第 1 次失败" in warnings[0]
        assert "连续第 3 次失败" in warnings[1]

    def test_success_resets_counter_no_new_warning_same_day(
        self, tmp_path, monkeypatch, caplog
    ):
        """push 成功清零连续计数（当日已告警标记不动）：同日再失败不新
        告警，DEBUG 计数从 1 重计。"""
        repo, bare = _repo_with_upstream(tmp_path)
        _break_remote(repo, tmp_path)

        with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
            _bump_todo(repo)
            assert _commit_todo_marker(repo) is True  # 失败 WARNING 计数 1
            _git(repo, "remote", "set-url", "origin", str(bare))
            _bump_todo(repo)
            assert _commit_todo_marker(repo) is True  # 成功 → 计数清零
            _break_remote(repo, tmp_path)
            _bump_todo(repo)
            assert _commit_todo_marker(repo) is True  # 再失败：同日已告警

        warnings = [
            r.getMessage() for r in caplog.records if r.levelname == "WARNING"
        ]
        assert len(warnings) == 1
        debug_msgs = [
            r.getMessage() for r in caplog.records if r.levelname == "DEBUG"
        ]
        assert any("连续失败计数 1" in m for m in debug_msgs)


# ── 3.3 有 remote 单次 push 失败：常规 WARNING 文案 ───────────────


class TestSinglePushFailureWarning:
    def test_evolution_lane_warning_has_repo_path_and_stderr(
        self, tmp_path, monkeypatch, caplog
    ):
        repo, _bare = _repo_with_upstream(tmp_path)
        _break_remote(repo, tmp_path)
        _bump_todo(repo)
        base = _todo_commit_count(repo)

        with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
            assert _commit_todo_marker(repo) is True

        warnings = [
            r.getMessage() for r in caplog.records if r.levelname == "WARNING"
        ]
        assert len(warnings) == 1
        assert str(repo) in warnings[0]  # task 1.3：文案含项目根路径
        assert "nowhere.git" in warnings[0]  # stderr 尾部（远端路径逐字保留）
        # LC_ALL=C 保证 stderr 英文文案原样入日志
        assert "does not appear to be a git repository" in warnings[0]
        # commit 仍产生（push 失败降级不回滚提交语义）
        assert _todo_commit_count(repo) == base + 1

    def test_self_review_lane_warning_has_repo_path(self, tmp_path, monkeypatch):
        repo, _bare = _repo_with_upstream(tmp_path)
        _break_remote(repo, tmp_path)
        _bump_todo(repo)
        logger = RecLogger()
        sched = _make_scheduler(repo, logger)
        base = _todo_commit_count(repo)

        assert sched._commit_todo("2026-10-30") is True

        warnings = logger.of_level("WARNING")
        assert len(warnings) == 1
        assert str(repo) in warnings[0]
        assert "nowhere.git" in warnings[0]
        assert _todo_commit_count(repo) == base + 1

    def test_self_review_lane_no_aggregation(self, tmp_path, monkeypatch):
        """design 边界：self_review 每日至多一次 push 无刷屏面，不聚合——
        连续失败各自记常规 WARNING（与 evolution 车道聚合行为分界）。"""
        repo, _bare = _repo_with_upstream(tmp_path)
        _break_remote(repo, tmp_path)
        logger = RecLogger()
        sched = _make_scheduler(repo, logger)

        _bump_todo(repo)
        assert sched._commit_todo("2026-10-30") is True
        _bump_todo(repo)
        assert sched._commit_todo("2026-10-30") is True

        assert len(logger.of_level("WARNING")) == 2
