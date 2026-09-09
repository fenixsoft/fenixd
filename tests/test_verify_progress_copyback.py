"""verify-progress 拷回（add-worktree-verify-progress-copyback）测试。

对应 spec/changes/add-worktree-verify-progress-copyback 的 tasks 2.1-2.4，
覆盖 spec verify-progress-copyback 的四条场景：
- 产物仅在 worktree 时拷回主树（逐字节一致、嵌套子目录递归）
- 主树已有所需文件时行为（mtime 守卫：worktree 较新覆盖、主树较新跳过、
  主树独有文件保留）
- 拷贝异常时 run 照常收工（fail-open：WARNING 落日志、不抛出）
- worktree 无产物目录（零动作、不创建主树目录、无日志）
"""

import os
from pathlib import Path

from core.agent_runner import AgentRunner
from tests.helpers import FakeLogger


class RecordingLogger(FakeLogger):
    """记录型 logger：记录所有 warning 调用，供 fail-open 断言。"""

    def __init__(self):
        self.warnings = []

    def warning(self, *a, **k):
        self.warnings.append(a)


def make_runner(proot: Path, logger=None):
    """构造最小 AgentRunner 实例（不触发真实 __init__）。"""
    runner = AgentRunner.__new__(AgentRunner)
    runner.config = {}
    runner.worktree_manager = None
    runner.state_machine = None
    runner.project_root = proot
    runner.logger = logger or FakeLogger()
    runner._running_agents = {}
    return runner


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _mtime_ns(path: Path) -> int:
    return path.stat().st_mtime_ns


def _set_mtime(path: Path, ns: int) -> None:
    os.utime(path, ns=(ns, ns))


class TestCopybackSuccess:
    """Spec 场景「产物仅在 worktree 时拷回主树」。"""

    def test_worktree_only_artifacts_copied_byte_identical(self, tmp_path):
        proot = tmp_path / "proj"
        wt = tmp_path / "wt"
        runner = make_runner(proot)
        spec = "my-spec"

        # worktree 内独有产物：根文件 + 嵌套子目录（rglob 递归覆盖）
        wt_result = _write(
            wt / ".fenix" / "verify-progress" / spec / ".fenix-run-result.json",
            '{"status":"success"}',
        )
        _write(
            wt / ".fenix" / "verify-progress" / spec / "test_scenarios.json",
            '{"total":3}',
        )
        _write(
            wt / ".fenix" / "verify-progress" / spec / "nested" / "deep" / "log.txt",
            "deep-log-content",
        )
        # 加速：mtime 统一抬高，保证新写入文件时间戳无歧义
        for p in (wt / ".fenix" / "verify-progress" / spec).rglob("*"):
            if p.is_file():
                _set_mtime(p, wt_result.stat().st_mtime_ns)

        runner._copyback_verify_progress(wt, spec)

        root_vp = proot / ".fenix" / "verify-progress" / spec
        for rel in [".fenix-run-result.json", "test_scenarios.json",
                    "nested/deep/log.txt"]:
            dst = root_vp / rel
            assert dst.is_file(), f"missing copyback: {rel}"
            assert dst.read_bytes() == (wt / ".fenix" / "verify-progress" / spec / rel).read_bytes()
            # copy2 保留源 mtime
            assert _mtime_ns(dst) == _mtime_ns(
                wt / ".fenix" / "verify-progress" / spec / rel
            )

    def test_worktree_newer_overwrites_root(self, tmp_path):
        """worktree 版本 mtime 较新 → 覆盖主树文件且保留 worktree mtime。"""
        proot = tmp_path / "proj"
        wt = tmp_path / "wt"
        runner = make_runner(proot)
        spec = "my-spec"
        rel = ".fenix-run-result.json"

        root_file = _write(
            proot / ".fenix" / "verify-progress" / spec / rel,
            "old-root-content",
        )
        wt_file = _write(
            wt / ".fenix" / "verify-progress" / spec / rel,
            "new-wt-content",
        )
        # 主树 mtime 旧、worktree 新
        _set_mtime(root_file, 1_000_000_000_000_000_000)
        _set_mtime(wt_file, 2_000_000_000_000_000_000)

        runner._copyback_verify_progress(wt, spec)

        dst = proot / ".fenix" / "verify-progress" / spec / rel
        assert dst.read_text(encoding="utf-8") == "new-wt-content"
        assert _mtime_ns(dst) == _mtime_ns(wt_file)


class TestCopybackMtimeGuard:
    """Spec 场景「主树已有所需文件时行为」。"""

    def test_root_newer_keeps_root_and_preserves_root_only_files(self, tmp_path):
        proot = tmp_path / "proj"
        wt = tmp_path / "wt"
        runner = make_runner(proot)
        spec = "my-spec"

        # 主树较新的冻结场景集替身——worktree 复用继承的陈旧版本不得覆盖
        root_scenarios = _write(
            proot / ".fenix" / "verify-progress" / spec / "test_scenarios.json",
            '{"frozen":true}',
        )
        _set_mtime(root_scenarios, 9_000_000_000_000_000_000)
        stale_wt = _write(
            wt / ".fenix" / "verify-progress" / spec / "test_scenarios.json",
            '{"stale":true}',
        )
        _set_mtime(stale_wt, 1_000_000_000_000_000_000)

        # 主树独有文件（框架簿记）：impl-result.json / warning_streaks.json 替身
        _write(
            proot / ".fenix" / "verify-progress" / spec / "impl-result.json",
            '{"impl":"keep-me"}',
        )
        _write(
            proot / ".fenix" / "verify-progress" / spec / "warning_streaks.json",
            '[1,2,3]',
        )

        runner._copyback_verify_progress(wt, spec)

        root_vp = proot / ".fenix" / "verify-progress" / spec
        # 主树较新 → 不被陈旧 worktree 覆盖
        assert root_vp.joinpath("test_scenarios.json").read_text(
            encoding="utf-8") == '{"frozen":true}'
        # 主树独有文件原样保留
        assert root_vp.joinpath("impl-result.json").read_text(encoding="utf-8") == '{"impl":"keep-me"}'
        assert root_vp.joinpath("warning_streaks.json").read_text(encoding="utf-8") == '[1,2,3]'

    def test_equal_mtime_prefers_root(self, tmp_path):
        """mtime 相等时保留主树版本（无 newer 信号不覆盖）。"""
        proot = tmp_path / "proj"
        wt = tmp_path / "wt"
        runner = make_runner(proot)
        spec = "my-spec"
        rel = "progress.json"

        root_file = _write(
            proot / ".fenix" / "verify-progress" / spec / rel, "root"
        )
        _write(
            wt / ".fenix" / "verify-progress" / spec / rel, "wt"
        )
        ts = 5_000_000_000_000_000_000
        _set_mtime(root_file, ts)
        _set_mtime(wt / ".fenix" / "verify-progress" / spec / rel, ts)

        runner._copyback_verify_progress(wt, spec)

        assert root_file.read_text(encoding="utf-8") == "root"


class TestCopybackFailOpen:
    """Spec 场景「拷贝异常时 run 照常收工」。"""

    def test_oserror_logs_warning_and_continues(self, tmp_path):
        proot = tmp_path / "proj"
        wt = tmp_path / "wt"
        logger = RecordingLogger()
        runner = make_runner(proot, logger=logger)
        spec = "my-spec"

        # worktree 内独有产物
        _write(
            wt / ".fenix" / "verify-progress" / spec / ".fenix-run-result.json",
            '{"status":"success"}',
        )
        _write(
            wt / ".fenix" / "verify-progress" / spec / "test_scenarios.json",
            '{"total":1}',
        )

        # 目标目录存在但不可写：用 /proc/self/fd 不可达路径模拟
        blocked_root = proot / ".fenix" / "verify-progress" / spec
        blocked_root.mkdir(parents=True, exist_ok=True)

        # mock shutil.copy2 让它在目标落在 blocked_root 时抛出 OSError
        import shutil as _shutil
        _orig_copy2 = _shutil.copy2
        def _failing_copy2(src, dst, *a, **kw):
            try:
                rel = Path(dst).relative_to(blocked_root)
            except ValueError:
                return _orig_copy2(src, dst, *a, **kw)
            raise OSError(f"Permission denied: {blocked_root}")

        _shutil.copy2 = _failing_copy2
        try:
            # 不应抛出（fail-open）
            runner._copyback_verify_progress(wt, spec)
        finally:
            _shutil.copy2 = _orig_copy2

        assert len(logger.warnings) >= 1, "expected >=1 WARNING for failed copyback"
        # WARNING 含 spec 名与源/目标路径（D3 可诊断）
        joined = " ".join(" ".join(map(str, w)) for w in logger.warnings)
        assert spec in joined
        assert ".fenix-run-result.json" in joined or "verify-progress" in joined
        # fail-open 继续处理其余文件：两条产物文件各自触发一条 WARNING
        assert len(logger.warnings) >= 2, (
            "fail-open should continue past first failure and warn per file"
        )


class TestCopybackZeroAction:
    """Spec 场景「worktree 无产物目录」。"""

    def test_no_dir_no_action_no_log(self, tmp_path):
        proot = tmp_path / "proj"
        wt = tmp_path / "wt"
        # 主树已存在 verify-progress 根（模拟既有簿记），spec 子目录不存在
        vp_root = proot / ".fenix" / "verify-progress"
        vp_root.mkdir(parents=True, exist_ok=True)
        (vp_root / "other-spec").mkdir()
        before = sorted(str(p.relative_to(vp_root)) for p in vp_root.rglob("*"))

        logger = RecordingLogger()
        runner = make_runner(proot, logger=logger)
        runner._copyback_verify_progress(wt, "my-spec")

        # 不创建 spec 目录、既有内容不变
        after = sorted(str(p.relative_to(vp_root)) for p in vp_root.rglob("*"))
        assert before == after
        assert not (proot / ".fenix" / "verify-progress" / "my-spec").exists()
        # 零日志
        assert logger.warnings == []
