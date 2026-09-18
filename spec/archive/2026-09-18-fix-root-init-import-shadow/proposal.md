# Proposal: fix-root-init-import-shadow

## Why

仓库根 `__init__.py`（08-16 `44e1443b` 迁移遗留，51B 纯注释）把 `/root/fenixd` 标记为同名包 `fenixd`，使 pytest 执行期 `sys.path` 命中 `/root` 时 `import fenixd` 被解析为该空包（无 `FenixDaemon`）而非守护脚本模块 `fenixd.py`。

该缺陷潜伏 26 天，制造了 5 例 `daemon_lifecycle` 存量失败，并催生 **4 处各自为政的散装 workaround**（模块级提前 import / `importlib.util` 绝对路径直载）。09-11 `d4978dbf` 只在受害者侧点修（`test_daemon_lifecycle_races.py` 改模块级 import），**根因工件 `__init__.py` 至今仍在**，雷区未除、无守卫拦截——任何新测试函数内的 `import fenixd`（如未跟踪探针 `tests/test_import_probe2.py`）仍会静默踩雷。每轮全量回归须先甄别此类非当前改动失败，污染解释。

## What Changes

- **根除**：删除仓库根 `__init__.py`（解除 `/root/fenixd` 的包标记），连带清除自举部署遗留的悬空符号链接 `.fenix/__init__.py`；删除后 `import fenixd` 在任一 `sys.path` 顺序下均自然落到 `fenixd.py` 模块。
- **守卫**：`tests/conftest.py` 新增收集期硬守卫——断言 `import fenixd` 绑定的是守护脚本模块（`__file__` basename 为 `fenixd.py` / 具备 `FenixDaemon`），把下游静默 AttributeError 提前为收集期显式失败。
- **收敛**：删除未跟踪探针残留 `tests/test_import_probe2.py`；改写 `tests/test_config.py`、`tests/test_spec_scheduling.py` 中因根因消除而失效的注释（其绝对路径直载的真实理由为模块隔离，非规避截胡）；保留并确认既有模块级 import 站点为自然正确写法。
- **回归锚点**：新增 `tests/test_import_isolation.py` 断言仓库根包标记缺失与 `fenixd` 模块身份。

## Capabilities

### New Capabilities
- `test-import-isolation`: 测试基座对 `import fenixd` 解析隔离的根除、收集期守卫、导入方式收敛与回归锚点

### Modified Capabilities
<!-- 无既有 capability 的 requirement 变更；归档中 core-package-structure / test-callsite-migration 等能力均不涉及本项 -->

## Impact

- **删除**：`__init__.py`（仓库根，git 跟踪，worktree 交付物）
- **修改**：`tests/conftest.py`（新增收集期守卫）、`tests/test_config.py`、`tests/test_spec_scheduling.py`（注释改写）
- **新增**：`tests/test_import_isolation.py`
- **主树侧运行时收尾**（非 git 交付物，worktree 内不可达，由 orchestrator 执行）：
  - `tests/test_import_probe2.py` 未跟踪探针残留——不存在于任何 worktree，已在立项前由主树侧删除
  - `.fenix/__init__.py` 自举部署遗留符号链接——仅在根 `__init__.py` 删除（merge 后）才悬空，merge-back 后清理
- **不改**：`core/`、`agents/`、dashboard 前端、生产运行路径（已核实生产侧无 `python -m fenixd` / `from fenixd import`，删除对生产零影响）
- **验证契约**：全量 pytest 必须保持全绿（基线 2651 passed）
