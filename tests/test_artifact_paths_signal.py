"""tests/test_artifact_paths_signal.py — 产物配置未裁决信号链路测试。

fix-artifact-paths-hardcoded-default D3 测试策略：
  1. _wip_overlap_gate 未裁决 → 写 build_artifact_paths_missing 信号
  2. has_build_artifacts=false → 已裁决，不写信号
  3. build_artifact_paths 非空 → 已裁决，不写信号
  4. 在途去重：同项目同 signal_type 未消费信号已存在 → 不重复写入
  5. _detect_family_explosion 从 evidence 项目名= 解析 spec 并唤起
  6. mark_escalated 防重复唤起
"""

import subprocess
from pathlib import Path

import pytest

from core.admin_store import AdminStore, SIGNAL
from core.worktree_manager import WorktreeManager

from test_agent_runner import FakeLogger
from test_worktree_merge_guard import git, init_repo


class _RecordingLogger:
    """记录型 logger（断言 warning 内容用，与 CapturingLogger 同构）。"""

    def __init__(self):
        self.warnings = []
        self.infos = []
        self.errors = []

    @staticmethod
    def _msg(a):
        return " ".join(str(x) for x in a if not isinstance(x, (dict, list)))

    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        self.infos.append(self._msg(a))

    def warning(self, *a, **k):
        self.warnings.append(self._msg(a))

    def error(self, *a, **k):
        self.errors.append(self._msg(a))


def make_wm(root: Path, **kwargs) -> WorktreeManager:
    base = root / ".claude" / "worktrees"
    base.mkdir(parents=True, exist_ok=True)
    return WorktreeManager(base, root, _RecordingLogger(), **kwargs)


def _seed_and_commit(root: Path) -> str:
    """写一个 tracked 文件并提交基线。"""
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "app.py").write_text("BASE\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "[fenix] base")
    return git(root, "rev-parse", "HEAD").stdout.strip()


def _branch_edit(root: Path, branch: str, edits: dict, base_sha: str):
    """从 base 派生分支提交 edits，checkout 回 base。"""
    git(root, "checkout", "-q", "-b", branch)
    for path, content in edits.items():
        (root / path).write_text(content, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", f"[fenix] branch {branch}")
    git(root, "checkout", "-q", base_sha)


# ── 1. 未裁决时信号写入 ─────────────────────────────────────────────────

class TestSignalWrittenWhenUnresolved:
    """config 未裁决 → _wip_overlap_gate 在早退前写信号。"""

    def test_unresolved_with_no_overlap_writes_signal(self, tmp_path):
        """主树干净（无 WIP 重叠）+ config 未裁决 → 信号仍被写入（早退前判定）。"""
        root = tmp_path / "repo"
        init_repo(root)
        base_sha = _seed_and_commit(root)
        # 分支改 src（有改动但主树无脏 → _detect_wip_overlap 空 → 早退）
        _branch_edit(root, "fenix/impl", {"src/app.py": "BRANCH\n"}, base_sha)

        wm = make_wm(root)  # 未配置 → 未裁决
        # 不做任何主树脏改动 → 无 WIP 重叠
        blocked, overlap = wm._wip_overlap_gate("fenix/impl")
        assert blocked is None
        assert overlap == [], "无重叠正常放行"

        # 信号已被写入（早退前触发）
        store = AdminStore(root, FakeLogger())
        signals = [
            r for r in store.read_all()
            if r.get("kind") == SIGNAL
            and r.get("signal_type") == "build_artifact_paths_missing"
        ]
        assert len(signals) == 1, f"应有 1 条未裁决信号: {signals}"
        assert "项目名=" in (signals[0].get("evidence") or "")
        assert "branch=fenix/impl" in (signals[0].get("evidence") or "")

    def test_unresolved_with_overlap_writes_signal(self, tmp_path):
        """主树脏 + 分支同改 → 有 WIP 重叠 + config 未裁决 → 信号被写入。"""
        root = tmp_path / "repo"
        init_repo(root)
        base_sha = _seed_and_commit(root)
        _branch_edit(root, "fenix/impl", {"src/app.py": "BRANCH\n"}, base_sha)
        # 主树脏改动 → WIP 重叠
        (root / "src" / "app.py").write_text("WIP\n", encoding="utf-8")

        wm = make_wm(root)
        blocked, overlap = wm._wip_overlap_gate("fenix/impl")
        # 有语义重叠（src/app.py 非产物）→ 重叠集合非空但 default auto → 放行
        assert blocked is None
        assert overlap == ["src/app.py"]

        store = AdminStore(root, FakeLogger())
        signals = [
            r for r in store.read_all()
            if r.get("kind") == SIGNAL
            and r.get("signal_type") == "build_artifact_paths_missing"
        ]
        assert len(signals) == 1


# ── 2. 已裁决（false）→ 不写信号 ──────────────────────────────────────────

class TestNoSignalWhenResolvedFalse:
    """has_build_artifacts=false → 已裁决无产物，不写信号。"""

    def test_false_no_signal(self, tmp_path):
        root = tmp_path / "repo"
        init_repo(root)
        base_sha = _seed_and_commit(root)
        _branch_edit(root, "fenix/impl", {"src/app.py": "BRANCH\n"}, base_sha)
        (root / "src" / "app.py").write_text("WIP\n", encoding="utf-8")

        wm = make_wm(root, build_artifact_paths=["dist/"], has_build_artifacts=False)
        wm._wip_overlap_gate("fenix/impl")

        store = AdminStore(root, FakeLogger())
        signals = [
            r for r in store.read_all()
            if r.get("kind") == SIGNAL
            and r.get("signal_type") == "build_artifact_paths_missing"
        ]
        assert signals == [], f"has=False 时不应写信号: {signals}"


# ── 3. 已裁决（路径非空）→ 不写信号 ──────────────────────────────────────

class TestNoSignalWhenPathsPresent:
    """build_artifact_paths 非空 → 已裁决，不写信号。"""

    def test_nonempty_paths_no_signal(self, tmp_path):
        root = tmp_path / "repo"
        init_repo(root)
        base_sha = _seed_and_commit(root)
        _branch_edit(root, "fenix/impl", {"src/app.py": "BRANCH\n"}, base_sha)
        (root / "src" / "app.py").write_text("WIP\n", encoding="utf-8")

        wm = make_wm(root, build_artifact_paths=["dist/"])
        wm._wip_overlap_gate("fenix/impl")

        store = AdminStore(root, FakeLogger())
        signals = [
            r for r in store.read_all()
            if r.get("kind") == SIGNAL
            and r.get("signal_type") == "build_artifact_paths_missing"
        ]
        assert signals == [], f"路径非空时不应写信号: {signals}"


# ── 4. 在途去重 ──────────────────────────────────────────────────────────

class TestSignalInflightDedup:
    """同项目同 signal_type 未消费信号已存在 → 不重复写入。"""

    def test_unresolved_twice_no_duplicate(self, tmp_path):
        root = tmp_path / "repo"
        init_repo(root)
        base_sha = _seed_and_commit(root)
        _branch_edit(root, "fenix/impl", {"src/app.py": "BRANCH\n"}, base_sha)
        (root / "src" / "app.py").write_text("WIP\n", encoding="utf-8")

        wm = make_wm(root)
        wm._wip_overlap_gate("fenix/impl")
        wm._wip_overlap_gate("fenix/impl")  # 第二次

        store = AdminStore(root, FakeLogger())
        signals = [
            r for r in store.read_all()
            if r.get("kind") == SIGNAL
            and r.get("signal_type") == "build_artifact_paths_missing"
        ]
        assert len(signals) == 1, f"在途去重应阻止重复写入: {signals}"

    def test_different_project_not_deduped(self, tmp_path):
        """不同项目名的信号互不影响。"""
        root1 = tmp_path / "repo1"
        root2 = tmp_path / "repo2"
        for r in [root1, root2]:
            init_repo(r)
        base_sha1 = _seed_and_commit(root1)
        _branch_edit(root1, "fenix/impl", {"src/app.py": "BRANCH\n"}, base_sha1)
        (root1 / "src" / "app.py").write_text("WIP\n", encoding="utf-8")

        base_sha2 = _seed_and_commit(root2)
        _branch_edit(root2, "fenix/impl", {"src/app.py": "BRANCH2\n"}, base_sha2)
        (root2 / "src" / "app.py").write_text("WIP2\n", encoding="utf-8")

        wm1 = make_wm(root1)
        wm2 = make_wm(root2)
        wm1._wip_overlap_gate("fenix/impl")
        wm2._wip_overlap_gate("fenix/impl")

        # 各自 store 里各有一条（不同文件）
        for root, label in [(root1, "root1"), (root2, "root2")]:
            store = AdminStore(root, FakeLogger())
            signals = [
                r for r in store.read_all()
                if r.get("kind") == SIGNAL
                and r.get("signal_type") == "build_artifact_paths_missing"
            ]
            assert len(signals) == 1, f"{label} 各自 store 应有 1 条信号"


# ── 5. admin_monitor 摄取与项目名解析 ──────────────────────────────────────

class TestSignalIngestion:
    """_detect_family_explosion 从 evidence 项目名= 解析 spec 并唤起。"""

    def test_evidence_project_name_parsed(self, tmp_path):
        """无 spec 的信号 → 从 evidence 项目名= 解析为 spec → 标记 escalated。"""
        from core.admin_monitor import AdminMonitor
        from core.state_machine import StateMachine

        root = tmp_path / "repo"
        init_repo(root)
        root.mkdir(exist_ok=True)
        logger = _RecordingLogger()
        sm = StateMachine(root / ".fenix" / "STATE.md", logger)
        # 注册 spec 以模拟活跃状态（避免终态守卫跳过）
        sm.add_spec("repo", {"priority": 10})
        sm.transition("repo", "ready")

        monitor = AdminMonitor({}, sm, root, logger)
        store = AdminStore(root, logger)
        # 手动写一条无 spec 信号
        store.append(
            {
                "kind": SIGNAL,
                "signal_type": "build_artifact_paths_missing",
                "spec": "",
                "severity": "major",
                "description": "test signal",
                "evidence": "项目名=repo; branch=fenix/impl",
                "recommended_action": "",
            }
        )
        signals = monitor._detect_family_explosion()
        assert len(signals) >= 1, "应摄取到 build_artifact_paths_missing 信号"
        found = any(
            s.get("signal_type") == "build_artifact_paths_missing"
            for s in signals
        )
        assert found, f"应包含 build_artifact_paths_missing 信号: {signals}"
        # 标记 escalated 后不重捞
        signals2 = monitor._detect_family_explosion()
        found2 = any(
            s.get("signal_type") == "build_artifact_paths_missing"
            for s in signals2
        )
        assert not found2, "escalated 后不应重捞"


# ── 6. 信号写入异常不抛穿 ──────────────────────────────────────────────────

class TestSignalWriteFailureDoesNotPropagate:
    """AdminStore.append 异常记 warning 不抛穿 merge-back。"""

    def test_store_write_error_does_not_block(self, tmp_path, monkeypatch):
        root = tmp_path / "repo"
        init_repo(root)
        base_sha = _seed_and_commit(root)
        _branch_edit(root, "fenix/impl", {"src/app.py": "BRANCH\n"}, base_sha)
        (root / "src" / "app.py").write_text("WIP\n", encoding="utf-8")

        wm = make_wm(root)
        original_append = AdminStore.append

        def failing_append(self, entry):
            raise IOError("simulated disk failure")

        monkeypatch.setattr(AdminStore, "append", failing_append, raising=True)
        try:
            blocked, overlap = wm._wip_overlap_gate("fenix/impl")
            # 不应抛穿；闸门行为不变
            assert blocked is None or hasattr(blocked, "wip_gate_blocked")
            # 应有 warning 日志
            warns = [w for w in wm.logger.warnings if "信号写入失败" in w]
            assert len(warns) >= 1, f"应记录信号写入失败警告: {wm.logger.warnings}"
        finally:
            monkeypatch.setattr(AdminStore, "append", original_append, raising=True)
