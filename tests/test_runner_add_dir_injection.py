"""tests/test_runner_add_dir_injection.py
--add-dir 车道化注入测试（fix-impl-code-review-writepath D2 / Task 4.1）。

断言 _run_claude 构造的 cmd：
① agent_type="implementer" 不含主树 verify-progress 的 --add-dir，
   且含 --add-dir <worktree>；
② agent_type="repair" 同 ①；
③ agent_type ∈ {verifier, planner-plan, planner-judge, fast-track}
   含主树 verify-progress 的 --add-dir；
④ agent_type=None（缺省）含主树 verify-progress 的 --add-dir（零行为变化）。

测试只捕获 cmd，不真起子进程。
"""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.agent_runner.runner import (
    _NO_MAIN_TREE_VERIFY_PROGRESS_LANES,
)


class _ImmediateProc:
    """立即结束的假进程，供 _run_claude 轮询环迅速退出。"""

    def __init__(self):
        self.returncode = 0
        self.stdout = MagicMock()
        self.stderr = MagicMock()
        self.stdout.readline = MagicMock(return_value="")  # EOF
        self.stderr.readline = MagicMock(return_value="")  # EOF

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def terminate(self):
        pass

    def kill(self):
        pass


def _capture_cmd(runner, cwd: Path, agent_type=None):
    """调 _run_claude，mock Popen 捕获 cmd。"""
    run_id = f"test-add-dir-{agent_type or 'none'}"
    progress_dir = runner.project_root / ".fenix" / "verify-progress"
    progress_dir.mkdir(parents=True, exist_ok=True)
    runs_dir = runner.project_root / ".fenix" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    captured = {}
    proc = _ImmediateProc()

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        return proc

    with patch("core.agent_runner.runner.subprocess.Popen", side_effect=fake_popen):
        runner._run_claude(
            prompt="test",
            cwd=cwd,
            run_id=run_id,
            spec_name="test-spec",
            agent_type=agent_type,
        )
    return captured["cmd"]


class TestAddDirInjection:
    """_run_claude --add-dir 条件注入断言。"""

    def test_constant_defined(self):
        """_NO_MAIN_TREE_VERIFY_PROGRESS_LANES 包含预期车道。"""
        assert "implementer" in _NO_MAIN_TREE_VERIFY_PROGRESS_LANES
        assert "repair" in _NO_MAIN_TREE_VERIFY_PROGRESS_LANES
        assert "spec-review" in _NO_MAIN_TREE_VERIFY_PROGRESS_LANES
        for lane in ("verifier", "planner-plan", "planner-judge", "fast-track",
                      "dispute-judge", "administrator"):
            assert lane not in _NO_MAIN_TREE_VERIFY_PROGRESS_LANES

    def test_implementer_no_main_tree_add_dir(self, tmp_path):
        """agent_type=implementer：不含主树 verify-progress --add-dir，含 --add-dir <cwd>。"""
        from tests.helpers import create_temp_project, make_runner
        project_root = create_temp_project(str(tmp_path / "proj"))
        runner = make_runner(project_root)
        cwd = tmp_path / "wt"
        cwd.mkdir()
        cmd = _capture_cmd(runner, cwd, agent_type="implementer")
        vp_dir = project_root / ".fenix" / "verify-progress"
        add_dirs = [cmd[i + 1] for i in range(len(cmd) - 1) if cmd[i] == "--add-dir"]
        assert str(cwd) in add_dirs, f"--add-dir {cwd} missing from cmd"
        assert str(vp_dir) not in add_dirs, f"--add-dir {vp_dir} should not be in cmd for implementer"

    def test_repair_no_main_tree_add_dir(self, tmp_path):
        """agent_type=repair：同 implementer 行为。"""
        from tests.helpers import create_temp_project, make_runner
        project_root = create_temp_project(str(tmp_path / "proj"))
        runner = make_runner(project_root)
        cwd = tmp_path / "wt"
        cwd.mkdir()
        cmd = _capture_cmd(runner, cwd, agent_type="repair")
        vp_dir = project_root / ".fenix" / "verify-progress"
        add_dirs = [cmd[i + 1] for i in range(len(cmd) - 1) if cmd[i] == "--add-dir"]
        assert str(cwd) in add_dirs
        assert str(vp_dir) not in add_dirs

    def test_has_main_tree_lanes_keep_add_dir(self, tmp_path):
        """③ agent_type ∈ {verifier, planner-plan, planner-judge, fast-track}：
        含主树 verify-progress --add-dir（确有其落点的车道注入保留）。"""
        from tests.helpers import create_temp_project, make_runner

        project_root = create_temp_project(str(tmp_path / "proj"))
        runner = make_runner(project_root)
        cwd = tmp_path / "wt"
        cwd.mkdir()
        vp_dir = project_root / ".fenix" / "verify-progress"
        for agent_type in (
            "verifier", "planner-plan", "planner-judge", "fast-track",
            "dispute-judge", "administrator",
        ):
            cmd = _capture_cmd(runner, cwd, agent_type=agent_type)
            add_dirs = [cmd[i + 1] for i in range(len(cmd) - 1) if cmd[i] == "--add-dir"]
            assert str(vp_dir) in add_dirs, (
                f"--add-dir {vp_dir} missing from cmd for {agent_type}"
            )

    def test_none_agent_type_has_main_tree_add_dir(self, tmp_path):
        """agent_type=None（缺省）：含主树 verify-progress --add-dir（零行为变化）。"""
        from tests.helpers import create_temp_project, make_runner
        project_root = create_temp_project(str(tmp_path / "proj"))
        runner = make_runner(project_root)
        cwd = tmp_path / "wt"
        cwd.mkdir()
        cmd = _capture_cmd(runner, cwd, agent_type=None)
        vp_dir = project_root / ".fenix" / "verify-progress"
        add_dirs = [cmd[i + 1] for i in range(len(cmd) - 1) if cmd[i] == "--add-dir"]
        assert str(vp_dir) in add_dirs
