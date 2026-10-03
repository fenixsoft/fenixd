"""pm_engine 补丁缝契约测试（code-review 5f6893d372ae）。

锁定 core/pm_engine/__init__.py 末行 `from .engine import *` 的补丁缝契约。
该星导出是模块属性补丁（如 tests/test_deliverable_gate.py 的
`patch("core.pm_engine.subprocess.run", ...)`）的承重点，但其成立依赖两个
从未被测试守护的静默前提：

1. engine.py 不定义 `__all__` —— 一旦定义，`import *` 只转出 `__all__`
   列出的名字，engine.py 模块级导入的 subprocess 等不再转出到包命名空间；
2. engine.py 顶层对标准库保持 `import subprocess` 整模块导入形态 ——
   一旦改成 `from subprocess import run`，`core.pm_engine.subprocess`
   属性消失，patch 目标直接 AttributeError。

任一前提被破坏，断裂点都落在测试外部的生产补丁路径上（AttributeError:
<module 'core.pm_engine' ... has no attribute 'subprocess'>），难以归因。
本测试把断裂点前移为下述明确契约报错。
"""

import ast
import subprocess as _subprocess_mod
from pathlib import Path

import core.pm_engine

ROOT = Path(__file__).resolve().parent.parent
ENGINE_SRC = ROOT / "core" / "pm_engine" / "engine.py"

# 补丁缝承重点 + 同一转出面的其余 engine.py 顶层整模块导入名。
# subprocess 是全仓唯一被 patch 字符串实际引用的模块属性（grep 权威：
# tests/test_deliverable_gate.py `patch("core.pm_engine.subprocess.run")`）；
# 其余名字同经 `import *` 转出，属同一契约面，一并锁定防漂移。
PATCH_SEAM_MODULES = (
    "subprocess",
    "hashlib",
    "json",
    "os",
    "re",
    "tempfile",
    "threading",
    "time",
)


def _parse_engine_ast():
    return ast.parse(ENGINE_SRC.read_text(encoding="utf-8"), filename=str(ENGINE_SRC))


def _assignment_target_names(node):
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    names = []
    for target in targets:
        if isinstance(target, ast.Name):
            names.append(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            names.extend(
                elt.id for elt in target.elts if isinstance(elt, ast.Name))
    return names


class TestPatchSeamNamespace:
    def test_patched_module_attrs_visible_in_package_ns(self):
        """core.pm_engine 命名空间必须含被补丁引用的模块属性。

        断裂即说明 `from .engine import *` 的星导出转出面被破坏，
        `patch("core.pm_engine.subprocess.run", ...)` 类补丁将静默失效。
        """
        for name in PATCH_SEAM_MODULES:
            assert hasattr(core.pm_engine, name), (
                f"补丁缝断裂：core.pm_engine.{name} 不在包命名空间。"
                f"契约：core/pm_engine/__init__.py 的 `from .engine import *` "
                f"必须把 engine.py 的模块级导入名转出到包命名空间，"
                f"否则 patch(\"core.pm_engine.{name}.*\") 类模块属性补丁会在"
                f"生产补丁路径上 AttributeError。请恢复 engine.py 的"
                f"`import {name}` 整模块导入、且不定义 __all__。"
            )

    def test_subprocess_attr_is_real_module(self):
        """core.pm_engine.subprocess 必须仍是 subprocess 模块本身。

        若 engine.py 把 `import subprocess` 改成 `from subprocess import run`，
        该属性会变成 run 函数或消失，`patch("core.pm_engine.subprocess.run")`
        即静默断裂。
        """
        attr = getattr(core.pm_engine, "subprocess", None)
        assert attr is _subprocess_mod, (
            f"补丁缝断裂：core.pm_engine.subprocess 已不是 subprocess 模块"
            f"（实际为 {attr!r}）。契约：engine.py 顶层须保持"
            f"`import subprocess` 整模块导入，经 `from .engine import *` "
            f"转出模块对象本身，patch(\"core.pm_engine.subprocess.run\") "
            f"才能命中真实子进程模块。"
        )

    def test_engine_module_defines_no_dunder_all(self):
        """engine.py 不得定义 __all__。

        __all__ 一旦出现，`import *` 只转出 __all__ 内名字，
        subprocess 等模块级导入名随即从包命名空间消失（契约前提 1）。
        """
        tree = _parse_engine_ast()
        offenders = [
            f"line {node.lineno}"
            for node in ast.walk(tree)
            if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign))
            and "__all__" in _assignment_target_names(node)
        ]
        assert not offenders, (
            f"补丁缝断裂：core/pm_engine/engine.py 定义了 __all__"
            f"（{', '.join(offenders)}）。契约：engine.py 不得定义 __all__，"
            f"否则 `from .engine import *` 不再转出模块级导入名，"
            f"core.pm_engine.subprocess 等补丁缝属性静默消失。"
            f"如需收窄对外 API，请在 __init__.py 显式 re-export 并同步"
            f"迁移 patch(\"core.pm_engine.*\") 消费点。"
        )

    def test_engine_imports_subprocess_as_module_at_top_level(self):
        """engine.py 顶层必须以 `import subprocess` 整模块形态导入（契约前提 2）。"""
        tree = _parse_engine_ast()
        found = any(
            isinstance(node, ast.Import)
            and any(
                alias.name == "subprocess" and alias.asname is None
                for alias in node.names
            )
            for node in tree.body
        )
        assert found, (
            "补丁缝断裂：core/pm_engine/engine.py 顶层缺少裸 "
            "`import subprocess`。契约：subprocess 须以整模块导入形态出现在 "
            "engine.py 顶层（如 `from subprocess import run` 会使 "
            "core.pm_engine.subprocess 属性消失，"
            "patch(\"core.pm_engine.subprocess.run\") 静默失效）。"
        )
