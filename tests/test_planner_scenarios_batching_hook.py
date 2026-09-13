"""planner 出题分批落盘机械化强制 hook 测试（fix-planner-scenarios-batching-hook）。

背景：出题进度条（verification-phase-progress）依赖 planner 按「先骨架、
后分批补全」的节奏增长 test_scenarios.json（planner-plan.md 第 3 条）；
实测 planner（deepseek-v4-flash）无视提示词指令、thinking 复述了规则仍
一次性写全量，出题阶段进度条退化为长时间 0%。
本 hook（PreToolUse/Write）机械化该规则：目标文件不存在（首次落盘）且
写入内容中任一场景带非空 steps/assertions 时 deny，逼 agent 先落骨架。
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK_SCRIPT = REPO_ROOT / ".fenix" / "hooks" / "planner-scenario-batching.py"
AGENT_SETTINGS = REPO_ROOT / ".fenix" / "agent-settings.json"

# fix-run-hang-amplification 3.4：自举部署物（.fenix/hooks/*、.fenix/agent-settings.json）
# 仅存在于主树（gitignored），worktree 中缺失时整类 skip——skip 原因指明「自举物
# 未部署（worktree 预期形态）」，避免 worktree 验证把环境事实判为本 change 引入的
# 回归；主树存在时断言行为不变（_run_hook 的 AssertionError 兜底保留）。
_HOOK_BOOTSTRAP_MISSING = not (HOOK_SCRIPT.is_file() and AGENT_SETTINGS.is_file())

SCENARIOS_FILENAME = "test_scenarios.json"


def _skeleton(n=3):
    """骨架形态：全部场景 id/kind/description，steps/assertions 空数组。"""
    return [
        {"id": f"s{i}", "kind": "web", "description": f"场景{i}",
         "steps": [], "assertions": []}
        for i in range(n)
    ]


def _fleshed(n=3):
    """带肉形态：steps/assertions 非空（骨架落盘规则禁止的首次写入）。"""
    return [
        {"id": f"s{i}", "kind": "web", "description": f"场景{i}",
         "steps": [{"action": "navigate", "value": "http://x/#/p"}],
         "assertions": [{"type": "element_visible", "selector": ".a"}]}
        for i in range(n)
    ]


def _write_payload(file_path, content):
    return {"tool_name": "Write", "tool_input": {"file_path": file_path,
                                                 "content": content}}


def _run_hook(payload: dict, cwd: Path) -> str:
    if not HOOK_SCRIPT.is_file():
        raise AssertionError(
            f"hook 脚本未创建: {HOOK_SCRIPT.relative_to(REPO_ROOT)}")
    proc = subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True, text=True, timeout=10, cwd=str(cwd),
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"hook 脚本非零退出 {proc.returncode}: {proc.stderr[:200]}")
    return proc.stdout.strip()


@unittest.skipIf(
    _HOOK_BOOTSTRAP_MISSING,
    "自举物未部署（worktree 预期形态）：.fenix/hooks/planner-scenario-batching.py "
    "或 .fenix/agent-settings.json 缺失",
)
class TestPlannerScenariosBatchingHook(unittest.TestCase):
    """PreToolUse/Write：test_scenarios.json 首次落盘必须是骨架。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_first_write_fleshed_scenarios_denied(self):
        """首次落盘（文件不存在）含带肉场景 → deny。"""
        out = _run_hook(
            _write_payload(str(self.tmp / SCENARIOS_FILENAME),
                           json.dumps(_fleshed(), ensure_ascii=False)),
            self.tmp)
        decision = json.loads(out)["hookSpecificOutput"]["permissionDecision"]
        self.assertEqual(decision, "deny")

    def test_first_write_skeleton_allowed(self):
        """首次落盘为纯骨架（steps/assertions 全空）→ 放行。"""
        out = _run_hook(
            _write_payload(str(self.tmp / SCENARIOS_FILENAME),
                           json.dumps(_skeleton(), ensure_ascii=False)),
            self.tmp)
        self.assertEqual(out, "{}")

    def test_overwrite_existing_file_allowed(self):
        """骨架已落（文件已存在）→ 后续全量重写放行（分批补全）。"""
        target = self.tmp / SCENARIOS_FILENAME
        target.write_text(json.dumps(_skeleton(), ensure_ascii=False),
                          encoding="utf-8")
        out = _run_hook(
            _write_payload(str(target),
                           json.dumps(_fleshed(), ensure_ascii=False)),
            self.tmp)
        self.assertEqual(out, "{}")

    def test_unrelated_path_allowed(self):
        """非 test_scenarios.json 的写入不拦。"""
        out = _run_hook(
            _write_payload(str(self.tmp / "other.json"),
                           json.dumps(_fleshed(), ensure_ascii=False)),
            self.tmp)
        self.assertEqual(out, "{}")

    def test_non_write_tool_allowed(self):
        """非 Write 工具（如 Edit）不在拦截范围。"""
        payload = {"tool_name": "Edit",
                   "tool_input": {"file_path": str(self.tmp / SCENARIOS_FILENAME),
                                  "new_string": "x"}}
        self.assertEqual(_run_hook(payload, self.tmp), "{}")

    def test_malformed_stdin_allowed(self):
        """stdin 非 JSON → 放行（fail-open）。"""
        proc = subprocess.run(
            [sys.executable, str(HOOK_SCRIPT)],
            input="not-json{{", capture_output=True, text=True,
            timeout=10, cwd=str(self.tmp),
        )
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "{}")

    def test_unparseable_content_fail_open(self):
        """写入内容不可解析（非 JSON 场景数组）→ 放行（验收门兜底）。"""
        out = _run_hook(
            _write_payload(str(self.tmp / SCENARIOS_FILENAME), "garbage"),
            self.tmp)
        self.assertEqual(out, "{}")

    def test_dict_wrapped_scenarios_denied(self):
        """dict 包裹形态 {"scenarios": [...]} 同样校验。"""
        out = _run_hook(
            _write_payload(str(self.tmp / SCENARIOS_FILENAME),
                           json.dumps({"scenarios": _fleshed()},
                                      ensure_ascii=False)),
            self.tmp)
        decision = json.loads(out)["hookSpecificOutput"]["permissionDecision"]
        self.assertEqual(decision, "deny")

    def test_missing_file_path_allowed(self):
        """无 file_path 的畸形输入 → 放行。"""
        out = _run_hook({"tool_name": "Write", "tool_input": {}}, self.tmp)
        self.assertEqual(out, "{}")

    def test_hook_registered_in_agent_settings(self):
        """agent-settings.json 已注册本 hook（部署守卫，防脚本在未挂载）。"""
        settings = json.loads(AGENT_SETTINGS.read_text(encoding="utf-8"))
        commands = [
            h.get("command", "")
            for entry in (settings.get("hooks", {}).get("PreToolUse") or [])
            for h in (entry.get("hooks") or [])
        ]
        self.assertTrue(
            any("planner-scenario-batching.py" in c for c in commands),
            f"agent-settings.json 未注册 planner-scenario-batching hook: {commands}")


if __name__ == "__main__":
    unittest.main()
