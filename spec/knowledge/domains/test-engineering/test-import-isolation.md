<!-- knowledge: capability=test-import-isolation rev=2 sources=spec/archive/2026-09-18-fix-root-init-import-shadow,spec/knowledge/_inbox/done/supervisor-import-time-argv-guard-trap.md -->

# 测试导入隔离

`import` 期两类陷阱的防护：模块身份保障（仓库根不得成为同名包截胡守护脚本模块）与导入期副作用安全（被 pytest/工具导入的模块须能在任意宿主 argv 下存活）。

## 现行规则

- 仓库根不得含 `__init__.py`（或任何使仓库根被解析为同名包 `fenixd` 的包标记）：`import fenixd` 在任一 `sys.path` 顺序下均须解析到守护脚本模块 `fenixd.py` 而非同名空包。
- `.fenix/__init__.py`（若存在）不得指向已删除的仓库根 `__init__.py`；悬空符号链接清除。
- `tests/conftest.py` 在收集期断言 `import fenixd` 绑定的是守护脚本模块（`__file__` basename 为 `fenixd.py`，或模块具备 `FenixDaemon`）；被同名包截胡时以显式硬失败终止收集（错误信息指明截胡），禁止降级为测试函数执行期的静默 `AttributeError`；正常态守卫静默放行。
- 导入方式收敛：纯为规避截胡而存在的 workaround 随根因消除而移除或改写为自然导入；因模块隔离（不污染 `sys.modules['fenixd']`）而保留的 `importlib.util` 绝对路径直载，注释归因须写模块隔离理由，不得残留已失效的截胡归因；未跟踪的探针残留文件（如 `tests/test_import_probe2.py`）不得存在。
- 回归锚点：`tests/test_import_isolation.py` 专属回归测试常驻，断言仓库根包标记缺失与 `fenixd` 模块身份（`__file__` basename 为 `fenixd.py`、具备 `FenixDaemon`），缺陷复发时于测试层立即暴露。
- 模块导入期 MUST NOT 解析宿主进程 argv：脚本参数解析只属于真实 CLI 入口（`argv[0]` 为本脚本，含测试经 monkeypatch `sys.argv` 模拟 CLI 的形态）；被测试/工具导入的模块，其导入期副作用必须能在任意宿主 argv 下存活。落点：`bin/fenixd_supervisor.py` 的 `_resolve_project_root()` 在模块导入期执行（`PROJECT_ROOT` 于导入期赋值），仅当 `Path(sys.argv[0]).name == "fenixd_supervisor.py"` 才消费 argv；宿主进程一律 `parse_known_args([])` 跳过解析、按 `FENIX_PROJECT_ROOT`/cwd 兜底（pytest argv 从不含 `--project-root`，跳过解析与逐字解析结果同为 None）。
- 导入链上的参数校验守卫不得对宿主参数开火：拼写近似守卫（unknown 参数分隔符归一后同时含 proj 与 root 子串即判拼错的 `--project-root` 并 `sys.exit(2)`）只允许在真实 CLI 入口路径执行。pytest 注入的 `--basetemp=<绝对路径>` 恒含 `/root/`（root），叠加 worktree 名含 project（proj）即两段齐备——宿主参数被误判为拼写错误即导入期 `SystemExit`。此类路径字符巧合只在 spec 名含相应字样的 worktree 全量回归中复现（主树 basetemp 路径不含 proj 不触发），对照组 worktree 正常运行不能作为无缺陷证据。
- pytest INTERNALERROR 秒败（整轮 exit 3）判因入口：`sys.exit()` 落在 import 链上时 pytest 以 INTERNALERROR 收敛整轮失败，秒败形态与端口/环境类伪失败高度同形，极易误归因为环境性失败；判因先看 INTERNALERROR 栈顶是否落在 `importtestmodule` 路径（被测测试文件的 import 语句），再谈环境。

## 代码锚点

- 主实现：`bin/fenixd_supervisor.py`（`_resolve_project_root()` 的 argv 消费门与拼写近似守卫）；`tests/conftest.py`（收集期模块身份守卫）
- 消费方（导入方测试）：`tests/test_supervisor_hosting.py`、`tests/test_stale_code_selfheal.py`、`tests/test_supervisor_log_single_write.py`、`tests/test_systemd_hosting.py`
- 守卫测试：`tests/test_import_isolation.py`（模块身份锚点）；argv 门无专属测试，由四个导入方测试文件的 `import bin.fenixd_supervisor`（宿主 pytest argv 下导入存活）天然充当回归锚点

## 溯源

- 2026-09-18 fix-root-init-import-shadow（spec/archive/2026-09-18-fix-root-init-import-shadow） — 消除仓库根 `__init__.py` 截胡 `import fenixd` 的根因，确立收集期硬失败守卫、导入方式收敛与专属回归锚点
- 2026-11-10 supervisor-import-time-argv-guard-trap（spec/knowledge/_inbox/done/supervisor-import-time-argv-guard-trap.md） — 折叠导入期 argv 解析陷阱：导入期禁解析宿主 argv（CLI 入口 argv[0] 门）、拼写近似守卫误击形态与 INTERNALERROR exit 3 判因
