"""
Tests for block-main-tree-write.py — worktree 隔离纵深 PreToolUse hook。

背景（2026-09-08 skill 基路径锚定事故）：implementer 调用 openspec-apply-change
后把 skill 注入文本首行的主树绝对路径锚定为项目根，39 次写盘全部落主树、
worktree 零改动。本 hook 对有 worktree 的 run 拦截主树写盘并给出纠偏处方。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HOOK = PROJECT_ROOT / ".fenix" / "hooks" / "block-main-tree-write.py"

# fix-run-hang-amplification 3.4：自举部署物（.fenix/hooks/*）仅存在于主树
# （gitignored），worktree 中缺失时整文件 skip——skip 原因指明「自举物未部署
# （worktree 预期形态）」，避免 worktree 验证把环境事实判为本 change 引入的
# 回归；主树存在时断言行为不变。
pytestmark = pytest.mark.skipif(
    not HOOK.is_file(),
    reason="自举物未部署（worktree 预期形态）：.fenix/hooks/block-main-tree-write.py 缺失",
)


def _run_hook(tool_input: dict, tool: str = "Write",
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
        input=json.dumps({"tool_name": tool, "tool_input": tool_input}),
        capture_output=True, text=True, env=env, timeout=10,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout or "{}")


def _env(root="/root/fenixd", wt="/root/fenixd/.claude/worktrees/impl-x-1"):
    return {"project_root": root, "worktree": wt}


def test_no_env_allows_everything():
    """无 worktree 的 run（env 缺失）→ 全放行，行为不变。"""
    assert _run_hook({"file_path": "/root/fenixd/core/x.py"}) == {}
    assert _run_hook({"file_path": "/root/fenixd/core/x.py"}, **_env()) != {}


def test_relative_path_allowed():
    """相对路径相对 CWD（=worktree）解析 → 放行。"""
    assert _run_hook({"file_path": "core/x.py"}, **_env()) == {}


def test_worktree_internal_absolute_allowed():
    """worktree 内绝对路径 → 放行。"""
    out = _run_hook(
        {"file_path": "/root/fenixd/.claude/worktrees/impl-x-1/core/x.py"},
        **_env())
    assert out == {}


def test_main_tree_write_denied_with_guidance():
    """主树绝对路径 → deny，且纠偏提示给出 worktree 内相对路径。"""
    out = _run_hook({"file_path": "/root/fenixd/core/x.py"}, **_env())
    decision = out["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    assert "core/x.py" in decision["blockReason"]
    assert "worktree" in decision["blockReason"]


def test_verify_progress_whitelist_allowed():
    """主树 verify-progress 目录（--add-dir 授权）→ 放行。"""
    out = _run_hook(
        {"file_path": "/root/fenixd/.fenix/verify-progress/myspec/progress.json"},
        **_env())
    assert out == {}


def test_outside_project_allowed():
    """主树之外的路径（/tmp 等）不归本防线管。"""
    assert _run_hook({"file_path": "/tmp/scratch.py"}, **_env()) == {}


def test_path_traversal_escape_denied():
    """worktree 内路径用 .. 逃逸到主树 → 拦截。"""
    out = _run_hook(
        {"file_path":
         "/root/fenixd/.claude/worktrees/impl-x-1/../../../core/x.py"},
        **_env())
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_edit_tool_also_guarded():
    """Edit 工具同样受防线保护（settings matcher 覆盖 Write|Edit|NotebookEdit）。"""
    out = _run_hook({"file_path": "/root/fenixd/core/x.py"},
                    tool="Edit", **_env())
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
