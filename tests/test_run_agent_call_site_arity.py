"""_run_agent 调用点元数契约（evo-api-stall-signal-grading 回归根因）。

背景（2026-10-15 事故）：dd78b1b82 把 ``_run_agent`` 返回值从 4 元扩为
5 元（追加 ``stall_latency``），runner.py 三处调用点同步改了，但
maintenance_runs.py 五处调用点（run_administrator / run_self_review /
run_evolution / run_code_review / run_code_fix）全部漏改——run 收尾即崩
``too many values to unpack (expected 4)``，整批条目被误记失败入
chain_skipped，车道空转重修（0/95 卡死 + 每批 ~13 美元白烧）。

这是同族第二烧：2026-09-05 已发生过 3→4 元同款崩溃（见
maintenance_runs.py run_administrator 调用点注释）。本契约把「调用点
解包宽度 == _run_agent 返回宽度」钉死，两侧任一方漂移即红。
"""

import ast
import unittest
from pathlib import Path

AGENT_RUNNER_DIR = Path(__file__).resolve().parent.parent / "core" / "agent_runner"


def _run_agent_return_widths():
    """从 runner.py 的 ``def _run_agent`` 收集返回元组宽度集合。"""
    tree = ast.parse((AGENT_RUNNER_DIR / "runner.py").read_text(encoding="utf-8"))
    widths = set()
    for node in ast.walk(tree):
        if not (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "_run_agent"):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Return) and isinstance(sub.value, ast.Tuple):
                widths.add(len(sub.value.elts))
    return widths


def _call_site_unpack_widths():
    """扫 agent_runner 包全部调用点：``= <...>_run_agent(...)`` 的解包宽度。

    返回 ``[(file, lineno, width), ...]``——只收录赋值目标为 Tuple 的形态
    （单名绑定/星号解包天然 arity 安全，不在此契约束缚面内）。
    """
    sites = []
    for py in sorted(AGENT_RUNNER_DIR.glob("**/*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Tuple)):
                continue
            value = node.value
            if not (isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute)
                    and value.func.attr == "_run_agent"):
                continue
            sites.append((py.name, node.lineno, len(node.targets[0].elts)))
    return sites


class TestRunAgentCallSiteArity(unittest.TestCase):
    """源码契约：全部 _run_agent 调用点解包宽度 == 返回元组宽度。"""

    def test_all_call_sites_match_return_arity(self):
        widths = _run_agent_return_widths()
        self.assertEqual(
            len(widths), 1,
            f"_run_agent 返回元组宽度不唯一（{sorted(widths)}）——多路返回"
            "形态会让调用点契约失义，先归一返回面",
        )
        arity = widths.pop()
        bad = [
            f"{name}:{lineno} 解包 {width} 元"
            for name, lineno, width in _call_site_unpack_widths()
            if width != arity
        ]
        self.assertFalse(
            bad,
            f"_run_agent 现返回 {arity} 元，以下调用点解包宽度不匹配"
            f"（run 收尾即崩 too many values to unpack，整批误判失败）: {bad}",
        )


class TestRunCodeFixAcceptsCurrentReturnShape(unittest.TestCase):
    """行为回归：5 元返回形态下 run_code_fix 成功路径不得崩。"""

    def test_success_path_with_5tuple_run_agent(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from test_code_fix import _item, _make_project_root, _make_runner
        from core.agent_runner.maintenance_runs import run_code_fix

        proot = _make_project_root()
        wt = proot / "wt-arity"
        (wt / ".fenix" / "code-review").mkdir(parents=True)
        # 合法产物行：2 fixed + 1 skipped（过产物硬门的「至少一条有效行」）
        out_path = wt / ".fenix" / "code-review" / "fix-out-code-fix-arity-1.jsonl"
        out_path.write_text(
            '{"item_id": "aaaaaaaaaaaa", "status": "fixed", "file": "a.py"}\n'
            '{"item_id": "bbbbbbbbbbbb", "status": "fixed", "file": "b.py"}\n'
            '{"item_id": "cccccccccccc", "status": "skipped", '
            '"skip_reason": "false_positive"}\n',
            encoding="utf-8",
        )
        runner = _make_runner(proot)
        runner._get_agent_model_assignment = lambda t: None
        runner._get_admin_model = lambda: "admin-model"

        def fake_run_agent(prompt, cwd, run_id, model_override=None,
                           env_overrides=None, **kw):
            # 与 runner.py _run_agent 成功终态同构：output, turns, session_id,
            # usage_info, stall_latency（evo-api-stall-signal-grading 起 5 元）
            return ("done", 3, "sess-1", {"input_tokens": 10, "output_tokens": 1},
                    {"rounds": 3, "stalls": 0, "max": 1.0})

        runner._run_agent = fake_run_agent

        res = run_code_fix(
            runner, wt, [_item("aaaaaaaaaaaa"), _item("bbbbbbbbbbbb"),
                         _item("cccccccccccc")],
            run_id="code-fix-arity-1",
        )
        self.assertTrue(
            res.success,
            f"5 元返回形态下 run_code_fix 不得失败（error={res.error!r}）",
        )
        self.assertEqual((res.fixed, res.skipped), (2, 1))


if __name__ == "__main__":
    unittest.main()
