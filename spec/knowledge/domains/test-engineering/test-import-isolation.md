<!-- knowledge: capability=test-import-isolation rev=1 sources=spec/archive/2026-09-18-fix-root-init-import-shadow -->

# 测试导入隔离

`import fenixd` 的模块身份保障：仓库根不得成为同名包，收集期守卫拦截截胡，避免守护脚本模块被空包替换后的静默失败。

## 现行规则

- 仓库根不得含 `__init__.py`（或任何使仓库根被解析为同名包 `fenixd` 的包标记）：`import fenixd` 在任一 `sys.path` 顺序下均须解析到守护脚本模块 `fenixd.py` 而非同名空包。
- `.fenix/__init__.py`（若存在）不得指向已删除的仓库根 `__init__.py`；悬空符号链接清除。
- `tests/conftest.py` 在收集期断言 `import fenixd` 绑定的是守护脚本模块（`__file__` basename 为 `fenixd.py`，或模块具备 `FenixDaemon`）；被同名包截胡时以显式硬失败终止收集（错误信息指明截胡），禁止降级为测试函数执行期的静默 `AttributeError`；正常态守卫静默放行。
- 导入方式收敛：纯为规避截胡而存在的 workaround 随根因消除而移除或改写为自然导入；因模块隔离（不污染 `sys.modules['fenixd']`）而保留的 `importlib.util` 绝对路径直载，注释归因须写模块隔离理由，不得残留已失效的截胡归因；未跟踪的探针残留文件（如 `tests/test_import_probe2.py`）不得存在。
- 回归锚点：`tests/test_import_isolation.py` 专属回归测试常驻，断言仓库根包标记缺失与 `fenixd` 模块身份（`__file__` basename 为 `fenixd.py`、具备 `FenixDaemon`），缺陷复发时于测试层立即暴露。

## 溯源

- 2026-09-18 fix-root-init-import-shadow（spec/archive/2026-09-18-fix-root-init-import-shadow） — 消除仓库根 `__init__.py` 截胡 `import fenixd` 的根因，确立收集期硬失败守卫、导入方式收敛与专属回归锚点
