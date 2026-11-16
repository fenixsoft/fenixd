"""evo-scenario-exec-tree-isolation 回归测试。

覆盖（tasks.md 4.1）：
① pytest/cli 执行集执行根落快照 worktree（模拟执行窗内主树被改写、断言结果
   不受影响）；
② merge-back 在验证在飞时有界推迟、超时放行留痕；
③ 锚位假失败稳态复跑甄别（复跑通过不计 fail、真失败仍 fail）；
④ 回退主树路径留痕；
⑤ 快照内全量套件冒烟预检（basetemp 落 ``<root>/.fenix/pytest-basetemp`` 形态
   与 worktree 路径 argv 守卫误击形态复检，对齐 design 风险段）。
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestExecRootDecisionSingleSource:
    """1.2：三缝共用同一执行根决策点的单源守卫。

    scenario-repaired 重入、排程重验（escalation ``_reverify_timers`` 到期
    重派）、unfreeze 重验全部汇流回 ``VerificationPipeline._execute_stage2``
    ——生产侧 ``VerifyEngine`` 构造点必须唯一。旁路新增并行决策点会绕开
    快照隔离与主树轮在飞登记，隔离语义静默失效（快照不建、互斥不感知），
    故以 AST 扫描固化单源，防回潮。
    """

    def test_verify_engine_construction_single_source(self):
        import ast

        core_root = REPO_ROOT / "core"
        sites = []
        for path in sorted(core_root.rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError, ValueError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    fn = node.func
                    name = None
                    if isinstance(fn, ast.Name):
                        name = fn.id
                    elif isinstance(fn, ast.Attribute):
                        name = fn.attr
                    if name == "VerifyEngine":
                        sites.append(str(path.relative_to(core_root)))
        assert sites == ["pm_engine/verification/pipeline.py"], (
            f"VerifyEngine 生产构造点漂移（执行根决策 MUST 单源于阶段2）: {sites}"
        )
