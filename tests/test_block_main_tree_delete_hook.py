"""
Tests for block-main-tree-delete.py — 主树 run 删除禁令 PreToolUse hook。

背景（2026-11-22 basetemp 事故）：每日自省 agent 主树裸跑 pytest 触发事故版
conftest rmtree 共享 basetemp 根，连续两晚把在飞全量回归批量打成 setup 假
失败。conftest 已修，本 hook 按硬行为机械化兜底原则拦主树 run 的删除类
Bash 命令（无 worktree 的 run：自省/admin 巡检/inplace 修复）。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HOOK = PROJECT_ROOT / ".fenix" / "hooks" / "block-main-tree-delete.py"

pytestmark = pytest.mark.skipif(
    not HOOK.is_file(),
    reason="自举物未部署（worktree 预期形态）：.fenix/hooks/block-main-tree-delete.py 缺失",
)


def _run_hook(command: str, tool: str = "Bash",
              project_root: str = "", worktree: str = "") -> dict:
    env = os.environ.copy()
    env.pop("FENIX_RUN_PROJECT_ROOT", None)
    env.pop("FENIX_RUN_WORKTREE", None)
    if project_root:
        env["FENIX_RUN_PROJECT_ROOT"] = project_root
    if worktree:
        env["FENIX_RUN_WORKTREE"] = worktree
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"tool_name": tool, "tool_input": {"command": command}}),
        capture_output=True, text=True, env=env, timeout=10,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout or "{}")


DENIED = [
    "rm -rf /root/fenixd/.fenix/pytest-basetemp",
    "rm -r build/",
    "rm stale.txt",
    "cd /root/fenixd && rm -rf .fenix && ls",
    "python3 -c \"import shutil; shutil.rmtree('/root/fenixd/.fenix')\"",
    "python3 -c \"import os; os.remove('/root/fenixd/x')\"",
    "python3 -c \"from pathlib import Path; Path('/tmp/x').unlink()\"",
    "git clean -fdx",
    "git rm -r cached_dir",
    "git worktree remove /root/fenixd/.claude/worktrees/impl-x",
    "find /root/fenixd -name '*.pyc' -delete",
    "find /tmp -empty -exec rm {} \\;",
    "unlink /root/fenixd/.fenix/pytest-basetemp",
]


@pytest.mark.parametrize("command", DENIED)
def test_main_tree_run_denies_deletion(command):
    """无 worktree（主树 run：自省/巡检/inplace）→ 删除命令全拦。"""
    out = _run_hook(command)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


ALLOWED = [
    # 自省正常核查形态：pytest 复跑（事故形态本身，conftest 已修，不拦）
    "python3 -m pytest tests/test_timelib_guard.py -q -p no:cacheprovider",
    "python3 -m pytest tests/ -q",
    # 只读核查
    "git log --oneline -5",
    "git diff HEAD~1 --stat",
    "cat .fenix/todo.md",
    # 写文件（归 block-main-tree-write 管，不归本防线）
    "python3 - <<'EOF'\nimport json\njson.dump({}, open('.fenix/self_review_out-x.json','w'))\nEOF",
    "echo done",
]


@pytest.mark.parametrize("command", ALLOWED)
def test_main_tree_run_allows_readonly_and_verification(command):
    """无 worktree → 只读核查/pytest 复跑/写文件放行。"""
    assert _run_hook(command) == {}


def test_worktree_run_allows_deletion():
    """有 worktree 的 run → 全放行（沙箱内删除归 worktree 语义管）。"""
    env = {"project_root": "/root/fenixd",
           "worktree": "/root/fenixd/.claude/worktrees/impl-x-1"}
    assert _run_hook("rm -rf build/", **env) == {}
    assert _run_hook("git clean -fdx", **env) == {}


def test_non_bash_tool_ignored():
    """非 Bash 工具不归本防线（Write/Edit 归 block-main-tree-write）。"""
    assert _run_hook("whatever", tool="Write") == {}


def test_malformed_input_passes_through():
    """非 JSON stdin / 空命令 → 放行（不阻断正常 run）。"""
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input="not-json", capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 0
    assert json.loads(proc.stdout or "{}") == {}
