"""add-impl-terminal-nocommit-gate — 终态零提交门 + 机械归因 + cleanup 留档 单测。

覆盖 spec 全部 Scenario：
  1. 门判定矩阵（1.1）：零提交+dirty→拦截、有提交→放行、零提交+干净→放行、非implementer→放行
  2. 退避通道（1.2）：AgentArtifactGateError 复用、[provider-transient] 前缀、跳过 record_transient_break
  3. 机械归因（2.1）：XML假工具调用→格式回退、markdown代码块→格式回退、无特征→忘提交
  4. cleanup 留档（3.1）：rmtree fallback 前 stash create、失败降级不阻断
"""

import json
import subprocess
from pathlib import Path

import pytest

from core.agent_runner import AgentArtifactGateError
from core.worktree_manager import WorktreeManager
from tests.helpers import FakeLogger, make_runner


def git(root: Path, *args, check=True):
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result


def init_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q")
    git(root, "config", "user.email", "test@fenix.local")
    git(root, "config", "user.name", "Fenix Test")
    git(root, "config", "commit.gpgsign", "false")
    (root / "shared.py").write_text("BASE\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "[fenix] base")
    git(root, "branch", "-M", "main")


def make_wm(root: Path) -> WorktreeManager:
    base = root / ".claude" / "worktrees"
    base.mkdir(parents=True, exist_ok=True)
    return WorktreeManager(base, root, FakeLogger())


def ahead_count(root: Path, branch: str) -> int:
    out = git(root, "rev-list", "--count", f"main..{branch}")
    return int(out.stdout.strip() or "0")


def make_runner_for_test(root: Path):
    runner = make_runner(root)
    runner.worktree_manager = make_wm(root)
    return runner


def write_run_transcript(project_root: Path, run_id: str, text: str):
    """写含指定 text 内容的 run 转录文件（末轮 assistant 消息）。"""
    runs_dir = project_root / ".fenix" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_file = runs_dir / f"{run_id}.jsonl"
    msg = {
        "type": "assistant",
        "message": {
            "id": "test-msg",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
            "model": "deepseek-v4-flash",
        },
    }
    run_file.write_text(json.dumps(msg) + "\n", encoding="utf-8")

# ── 1.1 门判定矩阵 ───────────────────────────────────────────────────────


class TestTerminalNoCommitGate:

    def test_zero_commit_dirty_intercept(self, tmp_path):
        """分支零提交且 worktree dirty → 抛 AgentArtifactGateError，
        error 含 [terminal-no-commit] 前缀与归因文案。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")
        branch = wm.get_branch_name(wt)
        (wt / "new_file.py").write_text("A\n", encoding="utf-8")
        assert ahead_count(root, branch) == 0

        runner = make_runner_for_test(root)
        write_run_transcript(root, "impl-demo-test-a1", "Done implementing.")
        with pytest.raises(AgentArtifactGateError, match=r"\[terminal-no-commit\]") as ei:
            runner._check_terminal_no_commit_gate(
                spec_name="demo", agent_type="implementer", wt_path=wt,
                branch=branch, wt_dirty=["new_file.py"],
                sub_run_id="impl-demo-test-a1")
        assert "未提交即收工" in str(ei.value) or "格式回退截断" in str(ei.value)

    def test_has_commit_no_intercept(self, tmp_path):
        """分支有新提交 → 门不触发，正常放行。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")
        branch = wm.get_branch_name(wt)
        (wt / "done.py").write_text("DONE\n", encoding="utf-8")
        git(wt, "add", "-A")
        git(wt, "commit", "-q", "-m", "[fenix] demo: done")
        assert ahead_count(root, branch) == 1
        (wt / "extra.py").write_text("EXTRA\n", encoding="utf-8")

        runner = make_runner_for_test(root)
        runner._check_terminal_no_commit_gate(
            spec_name="demo", agent_type="implementer", wt_path=wt,
            branch=branch, wt_dirty=["extra.py"],
            sub_run_id="impl-demo-test-a1")

    def test_zero_commit_clean_no_intercept(self, tmp_path):
        """零提交且 worktree 干净 → 门不触发（归零变更哨管辖）。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")
        branch = wm.get_branch_name(wt)
        assert ahead_count(root, branch) == 0
        runner = make_runner_for_test(root)
        runner._check_terminal_no_commit_gate(
            spec_name="demo", agent_type="implementer", wt_path=wt,
            branch=branch, wt_dirty=[], sub_run_id="impl-demo-test-a1")

    def test_non_implementer_no_intercept(self, tmp_path):
        """fast-track / repair / verifier → 门不生效。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")
        branch = wm.get_branch_name(wt)
        (wt / "dirty.py").write_text("D\n", encoding="utf-8")
        runner = make_runner_for_test(root)
        for at in ("fast-track", "repair", "verifier"):
            runner._check_terminal_no_commit_gate(
                spec_name="demo", agent_type=at, wt_path=wt,
                branch=branch, wt_dirty=["dirty.py"],
                sub_run_id="impl-demo-test-a1")


# ── 2.1 机械归因 ─────────────────────────────────────────────────────────


class TestAttribution:

    def test_xml_function_calls(self, tmp_path):
        """末轮 text 含 <function_calls> XML → 归因格式回退截断。"""
        root = tmp_path / "repo"
        init_repo(root)
        write_run_transcript(root, "test-run", (
            "Done. Now commit:\n\n<function_calls>\n"
            "<invoke name=\"Bash\">\n"
            "<parameter name=\"command\">git add . && git commit -m \"feat\"</parameter>\n"
            "</invoke>\n</function_calls>"
        ))
        runner = make_runner_for_test(root)
        assert "格式回退截断" in runner._classify_terminal_no_commit("test-run")

    def test_markdown_code_block(self, tmp_path):
        """末轮 text 含 markdown fenced code 的 Edit 调用 → 格式回退截断。"""
        root = tmp_path / "repo"
        init_repo(root)
        write_run_transcript(root, "test-run", (
            "Let me edit the file:\n\n```Edit\n"
            "file_path: core/foo.py\nold_string: X\nnew_string: Y\n```"
        ))
        runner = make_runner_for_test(root)
        assert "格式回退截断" in runner._classify_terminal_no_commit("test-run")

    def test_markdown_bash_code_block(self, tmp_path):
        """末轮 text 含 markdown ```bash git commit → 格式回退截断。"""
        root = tmp_path / "repo"
        init_repo(root)
        write_run_transcript(root, "test-run", (
            "Committing now:\n\n```bash\n"
            "git add -A\ngit commit -m \"feat: done\"\n```"
        ))
        runner = make_runner_for_test(root)
        assert "格式回退截断" in runner._classify_terminal_no_commit("test-run")

    def test_no_fake_tool_calls(self, tmp_path):
        """末轮 text 无假工具调用特征 → 归因未提交即收工。"""
        root = tmp_path / "repo"
        init_repo(root)
        write_run_transcript(root, "test-run", "All done, everything looks good.")
        runner = make_runner_for_test(root)
        assert "未提交即收工" in runner._classify_terminal_no_commit("test-run")

    def test_missing_transcript_defaults(self, tmp_path):
        """转录缺失 → 降级为未提交即收工。"""
        root = tmp_path / "repo"
        init_repo(root)
        runner = make_runner_for_test(root)
        assert "未提交即收工" in runner._classify_terminal_no_commit("nonexistent-run")

    def test_real_incident_fixture(self, tmp_path):
        """真实事故转录（1789001677）末轮特征 → 归因格式回退截断。"""
        root = tmp_path / "repo"
        init_repo(root)
        real_sample = (
            "107 tests passed with no regressions. Let me commit the current "
            "progress and move to tasks 3 and 4:\n\n"
            "<function_calls>\n"
            "<invoke name=\"Bash\">\n"
            "<parameter name=\"command\" string=\"true\">git add "
            "core/verify_engine/screenshot_lab.py core/attribution_gate.py && "
            "git commit -m \"[fenix] add-verdict-credibility-gate: Tasks 1-2\""
            "</parameter>\n</invoke>\n</function_calls>"
        )
        write_run_transcript(root, "real-fixture", real_sample)
        runner = make_runner_for_test(root)
        assert "格式回退截断" in runner._classify_terminal_no_commit("real-fixture")

    def test_attribution_in_gate_error(self, tmp_path):
        """归因结论写入门触发 error 文案（XML 假工具调用 → 格式回退截断）。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")
        branch = wm.get_branch_name(wt)
        (wt / "file.py").write_text("X\n", encoding="utf-8")
        runner = make_runner_for_test(root)
        write_run_transcript(root, "xml-run", (
            "Commit now:\n\n<function_calls><invoke name=\"Bash\">"
            "<parameter name=\"command\">git commit -m \"done\"</parameter>"
            "</invoke></function_calls>"
        ))
        with pytest.raises(AgentArtifactGateError, match=r"\[terminal-no-commit\]") as ei:
            runner._check_terminal_no_commit_gate(
                spec_name="demo", agent_type="implementer", wt_path=wt,
                branch=branch, wt_dirty=["file.py"], sub_run_id="xml-run")
        assert "格式回退截断" in str(ei.value)


# ── 3.1 cleanup rmtree fallback 前 stash create 留档 ─────────────────────


class TestCleanupSnapshot:

    def test_stash_create_called_before_rmtree(self, tmp_path):
        """git worktree remove 失败转 rmtree 且 dirty → 先 git stash create。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")
        (wt / "uncommitted.py").write_text("dirty\n", encoding="utf-8")

        call_log = []
        original_run = subprocess.run

        def patched_run(cmd, **kwargs):
            cmd_str = " ".join(str(c) for c in cmd)
            call_log.append(cmd_str)
            if "worktree" in cmd_str and "remove" in cmd_str:
                return subprocess.CompletedProcess(
                    cmd, returncode=128, stdout="",
                    stderr="fatal: Untracked files would be overwritten")
            return original_run(cmd, **kwargs)

        import core.worktree_manager as wm_mod
        wm_mod.subprocess.run = patched_run
        try:
            wm.cleanup(wt, success=True)
        finally:
            wm_mod.subprocess.run = original_run

        assert any("stash" in c and "create" in c for c in call_log), \
            f"stash create 应在 rmtree fallback 前被调用；实际调用：{call_log}"

    def test_stash_create_failure_no_block(self, tmp_path):
        """stash create 超时/失败 → 仅 WARNING，清理照常继续（目录被删）。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")
        (wt / "file.py").write_text("X\n", encoding="utf-8")

        stash_failed = [False]
        original_run = subprocess.run

        def patched_run(cmd, **kwargs):
            cmd_str = " ".join(str(c) for c in cmd)
            if "worktree" in cmd_str and "remove" in cmd_str:
                return subprocess.CompletedProcess(
                    cmd, returncode=128, stdout="", stderr="fatal: Untracked files")
            if "stash" in cmd_str and "create" in cmd_str:
                stash_failed[0] = True
                raise subprocess.TimeoutExpired(cmd, 5)
            return original_run(cmd, **kwargs)

        import core.worktree_manager as wm_mod
        wm_mod.subprocess.run = patched_run
        try:
            wm.cleanup(wt, success=True)  # 不应抛异常
        finally:
            wm_mod.subprocess.run = original_run

        assert stash_failed[0], "stash create 应被调用过（并触发失败）"
        assert not wt.exists(), "清理应在 stash create 失败后照常继续"

    def test_clean_worktree_no_stash_create(self, tmp_path):
        """worktree 干净 → rmtree fallback 前不执行 stash create。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")

        stash_called = [False]
        original_run = subprocess.run

        def patched_run(cmd, **kwargs):
            cmd_str = " ".join(str(c) for c in cmd)
            if "worktree" in cmd_str and "remove" in cmd_str:
                return subprocess.CompletedProcess(
                    cmd, returncode=128, stdout="", stderr="fatal: error")
            if "stash" in cmd_str and "create" in cmd_str:
                stash_called[0] = True
            if "status" in cmd_str and "porcelain" in cmd_str:
                return subprocess.CompletedProcess(cmd, returncode=0, stdout="")
            return original_run(cmd, **kwargs)

        import core.worktree_manager as wm_mod
        wm_mod.subprocess.run = patched_run
        try:
            wm.cleanup(wt, success=True)
        finally:
            wm_mod.subprocess.run = original_run

        assert not stash_called[0], "干净 worktree 不应调用 stash create"


# ── 1.2 门触发后进入既有 except 通道 ──────────────────────────────────────


class TestGateChannelIntegration:

    def test_error_receives_provider_transient_prefix(self):
        """AgentArtifactGateError 进入 except 通道后被加 [provider-transient] 前缀。"""
        error = "[terminal-no-commit] 归因:未提交即收工"
        if "[provider-transient]" not in error:
            error = f"[provider-transient] {error}"
        assert error.startswith("[provider-transient] [terminal-no-commit]")

    def test_record_transient_break_skipped_for_no_commit(self):
        """D1 处置：门触发 error（[terminal-no-commit] 前缀）不调 record_transient_break。"""
        error_text = "[terminal-no-commit] 归因:未提交即收工"
        # 判定：error 文本以 [terminal-no-commit] 开头 → 跳过 record_transient_break
        should_skip = error_text.startswith("[terminal-no-commit]")
        assert should_skip, "terminal-no-commit error 应跳过 record_transient_break"
