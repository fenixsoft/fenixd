"""fix-root-init-import-shadow 回归锚点。

仓库根 `__init__.py`（08-16 迁移遗留）曾把仓库根标记为同名包 `fenixd`，
使 pytest 执行期 `sys.path` 命中父目录时 `import fenixd` 解析到空包而非
守护脚本模块 `fenixd.py`，下游静默 `AttributeError: FenixDaemon`。

本文件断言根因工件已根除：仓库根不再含包标记，`import fenixd` 自然绑定
守护脚本模块。任何后续改动重新引入 `__init__.py` 都会在此立即暴露。
"""
import importlib
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent


def test_repo_root_has_no_package_marker():
    """仓库根 MUST NOT 含 `__init__.py`（包标记缺失）。"""
    assert not (repo_root / "__init__.py").exists(), (
        "仓库根存在 __init__.py：/root/fenixd 被标记为同名包 fenixd，"
        "`import fenixd` 会被截胡为空包。请删除之（fix-root-init-import-shadow）。"
    )


def test_import_fenixd_resolves_to_daemon_script_module():
    """`import fenixd` 的 `__file__` basename 必须为 `fenixd.py`。"""
    mod = importlib.import_module("fenixd")
    mod_file = Path(getattr(mod, "__file__", ""))
    assert mod_file.name == "fenixd.py", (
        f"import fenixd 解析到 {mod_file}，而非守护脚本模块 fenixd.py——"
        "被同名包截胡（仓库根 __init__.py）。"
    )


def test_fenixd_module_exposes_fenixdaemon():
    """守护模块必须具备 `FenixDaemon`（空包截胡时为静默 AttributeError）。"""
    mod = importlib.import_module("fenixd")
    assert hasattr(mod, "FenixDaemon"), (
        "fenixd 模块不具备 FenixDaemon：被同名包截胡为空包。"
    )


def test_fenixd_is_singleton_natural_import():
    """`import fenixd` 与 sys.modules 中的记录一致（自然导入即正确写法）。"""
    if "fenixd" in sys.modules:
        mod = sys.modules["fenixd"]
        assert Path(getattr(mod, "__file__", "")).name == "fenixd.py"
