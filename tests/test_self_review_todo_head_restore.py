"""回写前 HEAD 自愈（evo-self-review-todo-head-restore）测试。

台账 .fenix/todo.md 曾被整文件清空而回写路径读到空文件直接按空基线写，
历史内容从工作树与 HEAD 双重缺席。本文件覆盖：

- 2.1 四态：工作树空/缺失而 HEAD 非空（恢复基线后写入+WARNING）；工作树
  有内容（与现状一致不引 HEAD）；git show 失败（静默回退按空基线写）；
  todo_head_restore=false（不恢复无恢复 WARNING）。含 config 开关三态与
  _skip_review/_remove_resolved 同型接入。
- 2.2 dashboard 端点写入加锁与留痕（写成功 INFO、覆空 WARNING），形态
  对齐 tests/test_dashboard_todo_api.py。
"""

import logging
import subprocess

import pytest

from core.config import ConfigLoader
from core.self_review import SelfReviewScheduler
from tests.test_daily_self_review import FakeReviewResult, FakeSM

# HEAD 基线种子（2026-10-09 事故形态：历史台账入库后被清空工作树）
HEAD_BASELINE = "## 2026-10-08\n\n### 浪费\n\n- 旧条目：基线内容\n"
RESUME_MARK = "恢复基线"


class CapturingLogger:
    """记录调用留痕的 logger 替身（self.logger 双参口径，供 WARNING 断言）。"""

    def __init__(self):
        self.records = []

    def _rec(self, level, *a):
        self.records.append((level, " ".join(str(x) for x in a)))

    def debug(self, *a):
        self._rec("debug", *a)

    def info(self, *a):
        self._rec("info", *a)

    def warning(self, *a):
        self._rec("warning", *a)

    def error(self, *a):
        self._rec("error", *a)

    def warnings(self):
        return [m for lvl, m in self.records if lvl == "warning"]


@pytest.fixture()
def proot(tmp_path):
    root = tmp_path / "proj"
    (root / ".fenix").mkdir(parents=True)
    (root / "spec" / "changes").mkdir(parents=True)
    (root / ".fenix" / "STATE.md").write_text("# State\n\n## Specs\n\n", encoding="utf-8")
    return root


def _init_repo(proot):
    subprocess.run(["git", "init", "-q", "-b", "main", str(proot)], check=True)
    subprocess.run(["git", "-C", str(proot), "config", "user.email", "t@t.co"], check=True)
    subprocess.run(["git", "-C", str(proot), "config", "user.name", "test"], check=True)


def _commit_todo(proot, content):
    todo = proot / ".fenix" / "todo.md"
    todo.parent.mkdir(parents=True, exist_ok=True)
    todo.write_text(content, encoding="utf-8")
    subprocess.run(["git", "-C", str(proot), "add", "--", ".fenix/todo.md"], check=True)
    subprocess.run(["git", "-C", str(proot), "commit", "-qm", "seed todo"], check=True)


def make_sched(proot, logger=None, todo_head_restore=None):
    sr = {"enabled": True, "run_at": "02:00", "read_todo": False}
    if todo_head_restore is not None:
        sr["todo_head_restore"] = todo_head_restore
    config = {"admin": {"enabled": True, "self_review": sr}}
    return SelfReviewScheduler(
        config, proot, logger or CapturingLogger(), FakeSM(), agent_runner=None
    )


def _read_todo(proot):
    return (proot / ".fenix" / "todo.md").read_text(encoding="utf-8")


# ── 2.1 四态（经 _append_todo 主回写路径） ────────────────


class TestHeadRescueFourStates:
    """R1/R2：回写前自愈四态。"""

    def test_empty_worktree_restored_from_head(self, proot):
        """场景 1：工作树空而 HEAD 非空 → 恢复基线后追加 + 恢复 WARNING。"""
        _init_repo(proot)
        _commit_todo(proot, HEAD_BASELINE)
        (proot / ".fenix" / "todo.md").write_text("", encoding="utf-8")
        log = CapturingLogger()
        make_sched(proot, log)._append_todo("2026-10-10", FakeReviewResult(waste=["新浪费条目"]))
        text = _read_todo(proot)
        # 基线恢复 + 新节追加（落盘内容 = HEAD 版 + 新节）
        assert "## 2026-10-08" in text
        assert "旧条目：基线内容" in text
        assert "## 2026-10-10" in text
        assert "新浪费条目" in text
        # 恢复 WARNING：恰一条，含恢复字节数与豁免提示
        restores = [w for w in log.warnings() if RESUME_MARK in w]
        assert len(restores) == 1
        assert "字节" in restores[0]
        assert "todo_head_restore=false" in restores[0]

    def test_missing_worktree_restored_from_head(self, proot):
        """场景 1 缺失形态：工作树文件不存在同型恢复（R1 空/缺失两形态）。"""
        _init_repo(proot)
        _commit_todo(proot, HEAD_BASELINE)
        (proot / ".fenix" / "todo.md").unlink()
        log = CapturingLogger()
        make_sched(proot, log)._append_todo("2026-10-10", FakeReviewResult(waste=["新浪费条目"]))
        text = _read_todo(proot)
        assert "旧条目：基线内容" in text
        assert "## 2026-10-10" in text
        assert any(RESUME_MARK in w for w in log.warnings())

    def test_nonempty_worktree_untouched(self, proot):
        """场景 2：工作树有内容 → 与现状一致（增量追加），不引 HEAD 无恢复 WARNING。"""
        _init_repo(proot)
        _commit_todo(proot, HEAD_BASELINE)
        (proot / ".fenix" / "todo.md").write_text(
            "## 2026-10-09\n\n### 浪费\n\n- 手工条目\n", encoding="utf-8"
        )
        log = CapturingLogger()
        make_sched(proot, log)._append_todo("2026-10-10", FakeReviewResult(waste=["X"]))
        text = _read_todo(proot)
        assert "手工条目" in text  # 工作树内容逐字保留
        assert "旧条目：基线内容" not in text  # 未引 HEAD
        assert "## 2026-10-10" in text
        assert not [w for w in log.warnings() if RESUME_MARK in w]

    def test_git_show_failure_falls_back_to_empty_baseline(self, proot):
        """场景 3：git show 失败（仓库无提交）→ 静默回退按空基线写，无恢复 WARNING。"""
        _init_repo(proot)  # 无任何提交 → HEAD:.fenix/todo.md 必失败
        log = CapturingLogger()
        make_sched(proot, log)._append_todo("2026-10-10", FakeReviewResult(waste=["X"]))
        text = _read_todo(proot)
        assert "## 2026-10-10" in text
        assert "## 2026-10-08" not in text
        assert not [w for w in log.warnings() if RESUME_MARK in w]

    def test_non_git_project_falls_back(self, proot):
        """场景 3 非 git 分支：项目非 git 仓库同型静默回退，回写不阻塞。"""
        log = CapturingLogger()
        make_sched(proot, log)._append_todo("2026-10-10", FakeReviewResult(waste=["X"]))
        text = _read_todo(proot)
        assert "## 2026-10-10" in text
        assert not [w for w in log.warnings() if RESUME_MARK in w]

    def test_restore_disabled_skips_rescue(self, proot):
        """场景 4：todo_head_restore=false → 不恢复、按空基线写、无恢复 WARNING。"""
        _init_repo(proot)
        _commit_todo(proot, HEAD_BASELINE)
        (proot / ".fenix" / "todo.md").write_text("", encoding="utf-8")
        log = CapturingLogger()
        make_sched(proot, log, todo_head_restore=False)._append_todo(
            "2026-10-10", FakeReviewResult(waste=["X"])
        )
        text = _read_todo(proot)
        assert "旧条目：基线内容" not in text
        assert "## 2026-10-10" in text
        assert not [w for w in log.warnings() if RESUME_MARK in w]


# ── 1.2 配置开关三态 ──────────────────────────────────────


class TestConfigSwitch:
    """get_self_review_config：缺省 true / 显式 false / 非 bool 回退缺省。"""

    def test_default_true(self):
        assert ConfigLoader.get_self_review_config({})["todo_head_restore"] is True

    def test_explicit_false(self):
        cfg = {"admin": {"self_review": {"todo_head_restore": False}}}
        assert ConfigLoader.get_self_review_config(cfg)["todo_head_restore"] is False

    def test_non_bool_falls_back_default(self):
        for bad in ("yes", 1, None):
            cfg = {"admin": {"self_review": {"todo_head_restore": bad}}}
            assert ConfigLoader.get_self_review_config(cfg)["todo_head_restore"] is True, bad


# ── 1.1 三处回写接入（_skip_review / _remove_resolved 同型） ──


class TestHeadRescueOtherWriters:
    """_skip_review / _remove_resolved 经同一助手取基线。"""

    def test_skip_review_rescues_baseline(self, proot):
        """零活动占位写入前同样恢复基线（基线 + 占位节）。"""
        _init_repo(proot)
        _commit_todo(proot, HEAD_BASELINE)
        (proot / ".fenix" / "todo.md").write_text("", encoding="utf-8")
        log = CapturingLogger()
        make_sched(proot, log)._skip_review("2026-10-10")
        text = _read_todo(proot)
        assert "旧条目：基线内容" in text
        assert "自上次自省以来无 SPEC 活动" in text
        assert any(RESUME_MARK in w for w in log.warnings())

    def test_remove_resolved_matches_on_restored_baseline(self, proot):
        """闭环移除在恢复后的基线上匹配命中并重写（同型复用）。"""
        _init_repo(proot)
        _commit_todo(proot, HEAD_BASELINE)
        (proot / ".fenix" / "todo.md").write_text("", encoding="utf-8")
        log = CapturingLogger()
        sched = make_sched(proot, log)
        entries = [
            {
                "id": "2026-10-08#浪费#1",
                "date": "2026-10-08",
                "section": "浪费",
                "text": "旧条目：基线内容",
            }
        ]
        removed = sched._remove_resolved(
            entries, [{"id": "2026-10-08#浪费#1", "reason": "已闭环"}]
        )
        assert [r["id"] for r in removed] == ["2026-10-08#浪费#1"]
        assert "旧条目：基线内容" not in _read_todo(proot)
        assert any(RESUME_MARK in w for w in log.warnings())


# ── 2.2 dashboard 端点加锁与留痕 ─────────────────────────


class TestDashboardTodoEndpointGuard:
    """POST /api/todo：持同一把锁 + 成功 INFO / 覆空 WARNING（R3）。"""

    def test_post_success_logs_info_with_path_and_bytes(self, server_fx, caplog):
        proot, srv = server_fx
        with caplog.at_level(logging.INFO, logger="fenixd.dashboard.routes.settings_routes"):
            status, data = srv.post_json(
                "/api/todo?project=proj-a", {"content": "## 2026-10-10\n\n- 新内容\n"}
            )
        assert status == 200 and data["ok"] is True
        saved = proot / ".fenix" / "todo.md"
        assert saved.read_text(encoding="utf-8").startswith("## 2026-10-10")
        msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
        assert any("dashboard 覆写 todo.md" in m and "字节" in m for m in msgs)
        assert any(str(saved) in m for m in msgs)

    def test_post_acquires_todo_file_lock(self, server_fx):
        """todo.md 目标持 fs_utils 同一把 .todo.md.lock（锁文件落位）。"""
        proot, srv = server_fx
        srv.post_json("/api/todo?project=proj-a", {"content": "内容\n"})
        assert (proot / ".fenix" / ".todo.md.lock").is_file()

    def test_post_empty_content_with_head_nonempty_warns(self, server_fx, caplog):
        """覆空而 HEAD 版非空：保存照常成功（以 UI 为准）+ WARNING 留痕。"""
        proot, srv = server_fx
        _init_repo(proot)
        _commit_todo(proot, HEAD_BASELINE)
        with caplog.at_level(logging.WARNING, logger="fenixd.dashboard.routes.settings_routes"):
            status, data = srv.post_json("/api/todo?project=proj-a", {"content": ""})
        assert status == 200 and data["ok"] is True
        assert _read_todo(proot) == ""
        msgs = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("HEAD 版非空" in m and "字节" in m for m in msgs)

    def test_post_empty_content_non_git_no_warning_no_block(self, server_fx, caplog):
        """非 git 项目覆空：git show 失败跳过 HEAD 对比，保存不阻塞、无对比 WARNING。"""
        _, srv = server_fx
        with caplog.at_level(logging.WARNING, logger="fenixd.dashboard.routes.settings_routes"):
            status, data = srv.post_json("/api/todo?project=proj-a", {"content": ""})
        assert status == 200 and data["ok"] is True
        msgs = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
        assert not any("HEAD 版非空" in m for m in msgs)

    def test_post_nonempty_content_no_head_warning(self, server_fx, caplog):
        """覆写非空内容不触发覆空对比（仅覆空留痕）。"""
        proot, srv = server_fx
        _init_repo(proot)
        _commit_todo(proot, HEAD_BASELINE)
        with caplog.at_level(logging.WARNING, logger="fenixd.dashboard.routes.settings_routes"):
            status, data = srv.post_json(
                "/api/todo?project=proj-a", {"content": "## 2026-10-10\n\n- 全量替换\n"}
            )
        assert status == 200 and data["ok"] is True
        assert "全量替换" in _read_todo(proot)
        msgs = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
        assert not any("HEAD 版非空" in m for m in msgs)
