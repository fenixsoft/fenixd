"""
测试替身保真契约（fake-double fidelity contract）。

背景：2026-09-14 evo-item-retention-doc-tracking 事故——生产代码
``admin_monitor._reset_env_blocked_after_disposition`` 调用
``pm_engine.handle_event("spec_implemented", spec)``（少传第三参 ``spec_entry``），
必然抛 ``TypeError``；但测试替身写成 ``def handle_event(self, event_kind,
spec_name, **kwargs)``，``**kwargs`` 把实参数量不符**静默吸收**，断言
``handle_event_calls == [("spec_implemented", "demo")]`` 对 2 参/3 参都成立，
CI 全绿。该路径自 2026-09-11 引入起从未成功执行过，直到本 spec 首次走到
该分支才暴露（卡在 testing 1h12m）。

本守卫把「替身签名必须能承载生产签名」机械化：新增/修改任一 seam 方法的
替身后，若它比生产方法**更宽容**（多 ``*args``/``**kwargs``）或**必填参数更少**，
即失败——把「CI 全绿但代码是坏的」这一类静默盲区封死在提交时。

守卫范围（保守起步，宁缺勿滥）：
  - 生产侧候选 = core/ 下**方法名唯一**、且该唯一定义不含 ``*args``/``**kwargs``、
    非 dunder、不在宽泛名黑名单（logger 风格 ``info``/``warning``… 与容器风格
    ``get``/``items``…）中的方法。名字唯一即「同名即同契约」成立，避免把
    无关类的同名方法误判为同一 seam。
  - 测试侧扫描 tests/ 下所有类的同名方法，比对 (必填位置数, 是否有 *args,
    是否有 **kwargs)。判「危险」= 替身更宽容（有 *args/**kwargs）或必填更少。
  - 替身必填**更多**不判危险（会在测试里当场 TypeError，无静默风险）。

误报豁免：ALLOWLIST 用于显式豁免确有意为之的宽容替身（当前为空）。
"""
import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

REPO_ROOT = Path(__file__).resolve().parent.parent
CORE_DIR = REPO_ROOT / "core"
TESTS_DIR = REPO_ROOT / "tests"

# 宽泛方法名黑名单：这些名字在 core/ 里语义高度重叠（logger 风格 / 容器风格 /
# 时间工具），「同名即同契约」不成立，排除以免误报。
_DENY_NAMES = {
    "__init__", "info", "warning", "error", "debug", "critical", "exception",
    "log", "_log", "format", "get", "items", "keys", "values", "append",
    "update", "read", "write", "close", "send", "join", "start", "stop",
    "emit", "handle", "run", "call", "add", "pop", "clear", "copy", "sort",
    "now", "isoformat",
}

# 显式豁免：key = (tests 相对路径, 类名, 方法名)。当前为空——本守卫落地时
# 全部 seam 替身已收紧为忠实签名，无既有欠债。
_ALLOWLIST: set = set()


def _has_decorator(fn: ast.AST, name: str) -> bool:
    return any(
        isinstance(d, ast.Name) and d.id == name for d in fn.decorator_list
    )


def _signature(fn: ast.AST) -> tuple:
    """(必填位置参数个数, 是否有 *args, 是否有 **kwargs)。

    self/cls 按约定剥离——staticmethod 不剥（其首参是真实入参）。
    """
    a = fn.args
    named = [x.arg for x in (a.posonlyargs + a.args)]
    if not _has_decorator(fn, "staticmethod"):
        named = named[1:]
    return (len(named) - len(a.defaults), a.vararg is not None,
            a.kwarg is not None)


def _prod_candidates() -> dict:
    """生产侧 seam 候选：方法名 -> 唯一签名 (req, has_vararg, has_kwarg)。"""
    by_name: dict = {}
    for p in CORE_DIR.rglob("*.py"):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (SyntaxError, OSError):
            continue
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            for m in cls.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    by_name.setdefault(m.name, set()).add(_signature(m))
    out = {}
    for name, sigs in by_name.items():
        if len(sigs) != 1:
            continue
        if name.startswith("__") or name in _DENY_NAMES:
            continue
        sig = next(iter(sigs))
        if sig[1] or sig[2]:  # 生产方法自身变长 —— 无从约束
            continue
        out[name] = sig
    return out


def _scan_violations() -> list:
    """返回违约替身列表 [(rel_path, line, cls, method, fake_sig, prod_sig)]。"""
    cand = _prod_candidates()
    found = []
    for p in TESTS_DIR.rglob("*.py"):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (SyntaxError, OSError):
            continue
        rel = str(p.relative_to(REPO_ROOT))
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            for m in cls.body:
                if not isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if m.name not in cand:
                    continue
                if (rel, cls.name, m.name) in _ALLOWLIST:
                    continue
                fake = _signature(m)
                prod = cand[m.name]
                # 危险 = 替身更宽容（*args/**kwargs）或必填更少
                if fake[1] or fake[2] or fake[0] < prod[0]:
                    found.append((rel, m.lineno, cls.name, m.name, fake, prod))
    return found


class TestFakeDoubleFidelity(unittest.TestCase):
    """tests/ 中的 seam 替身签名必须能承载生产签名。"""

    def test_no_permissive_double_for_unique_prod_method(self):
        violations = _scan_violations()
        if violations:
            lines = [
                f"  {rel}:{ln} {cls}.{meth}  fake={fs} prod={ps}"
                for rel, ln, cls, meth, fs, ps in violations
            ]
            self.fail(
                "存在比生产方法更宽容的测试替身（*args/**kwargs 或必填参数更少）"
                "——会把生产侧实参数量不符静默吸收，令 CI 全绿而代码已坏"
                "（2026-09-14 evo-item-retention 事故根因）：\n"
                + "\n".join(lines)
            )

    def test_guard_has_teeth(self):
        """守卫有效性自检：候选集非空（否则规则退化，永远绿）。"""
        cand = _prod_candidates()
        self.assertGreater(
            len(cand), 100,
            f"seam 候选仅 {len(cand)} 个，规则可能已退化——检查 _DENY_NAMES/"
            "候选构造是否仍命中真实方法名",
        )


if __name__ == "__main__":
    unittest.main()
