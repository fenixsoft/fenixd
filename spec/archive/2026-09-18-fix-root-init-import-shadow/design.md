## Context

仓库根 `__init__.py`（`44e1443b` 08-16 迁移遗留，51B 纯注释）把 `/root/fenixd` 变成可导入的同名包 `fenixd`。当 pytest 执行期 `sys.path` 出现 `/root` 时，`import fenixd` 被解析为该空包（无 `FenixDaemon`），而非守护脚本模块 `fenixd.py`。

现状：
- 09-11 `d4978dbf` 仅在受害者侧点修（`test_daemon_lifecycle_races.py` 改模块级 import），根因工件仍在。
- 已存在 4 处散装 workaround：模块级提前 import（`test_daemon_lifecycle_races.py`、`test_impl_wip_checkpoint.py`、`test_interrupt_recovery_preserve.py`）与 `importlib.util` 绝对路径直载（`test_config.py::TestDaemonSingletonFlock`、`test_spec_scheduling.py::setUpClass`）。
- 未跟踪探针 `tests/test_import_probe2.py` 仍使用函数内 `import fenixd` 的危险模式。
- `.fenix/` 为自举部署的符号链接镜像（`.fenix/core`、`.fenix/tests`、`.fenix/fenixd.py`、`.fenix/__init__.py` → 仓库根同名文件），无代码重建源（部署时一次性创建）。

约束：生产侧无 `python -m fenixd` / `from fenixd import`（已核实），删除对生产零影响；全量回归基线 2651 passed。

## Goals / Non-Goals

**Goals:**
- 根除 `import fenixd` 撞包的物理条件（删除根包标记），使各测试无需 workaround 即可自然导入。
- 建立收集期守卫，把撞包从下游静默 `AttributeError` 变为收集期显式硬失败。
- 收敛导入方式，删除探针残留，修正失效注释。
- 补一条专属回归锚点。

**Non-Goals:**
- 不改动任何产品代码（`core/`、`agents/`、dashboard 前端、生产运行路径）。
- 不重构被测模块的导入方式以外的测试逻辑（不改断言、不改夹具语义）。
- 不引入 sys.path 运行时改写（不靠排序 hack 掩盖，而是消除包标记本身）。

## Decisions

### D1：根除手段 = 删除 `__init__.py`（非清空、非排序 hack）

- **删除**：移除包标记后，`/root/fenixd` 不再是包，`import fenixd` 在任一 `sys.path` 顺序下都落到 `fenixd.py`。
- 备选「清空为 0 字节」**否决**：0 字节仍是包标记，`import fenixd` 依旧绑定空包 → 依旧 `AttributeError`。
- 备选「在 conftest 里把 `/root` 移出 sys.path」**否决**：属排序 hack，其他工具/入口仍可复现，且掩盖而非消除根因。

### D2：守卫形态 = conftest 收集期硬失败

在 `tests/conftest.py` 的 `sys.path` 规范化**之后**、模块级加入守卫：断言 `import fenixd` 的 `__file__` basename 为 `fenixd.py` 或模块具备 `FenixDaemon`，否则 `raise ImportError`。conftest 在收集阶段被 pytest 导入，故硬失败早于任何测试函数执行。

- 备选「放进 session fixture」**否决**：fixture 在用例执行期才跑，晚于收集，无法在污染发生前拦截。
- 守卫判定取「basename 或 hasattr」的宽松并集：兼容不同 Python 打包形态，避免误伤。

### D3：收敛边界 = 只动理由已失效者

- **删除**：`tests/test_import_probe2.py`（未跟踪探针残留，纯为取证而生）。
- **改写注释**：`test_config.py`、`test_spec_scheduling.py` 的 `importlib.util` 直载——其真实且仍然成立的理由是**模块隔离**（以独立模块名 `fenixd_daemon_under_test` / `fenixd_scheduling_kick_under_test` 加载，不注册进 `sys.modules['fenixd']`，避免与其他测试互相串扰），截胡归因随根因消除而删去。直载方式**保留**。
- **保留并确认**：三处模块级 `import fenixd` 删除后即为自然正确写法，无需回退为函数内延迟 import。

### D4：删除动作的声明形态 = `kind: reference`

`tasks.md` 的 `## Deliverables` 声明段 kind 枚举仅 `new`/`modify`/`reference`，无 `delete`。删除目标若声明 `modify`，晋升 lint（主树存在性）当下通过，但收工守卫按「实现分支存在性」硬校验会因文件已删而误判缺件 → 打回循环。故删除目标声明为 `reference`：lint 时主树存在（通过），运行时守卫仅审计不参与缺件判定（不误拦）。注释显式说明「交付物是删除动作」。删除的最终强制由 `test_import_isolation.py` 的「根包标记缺失」断言承担。

## Risks / Trade-offs

- [删除根 `__init__.py` 可能牵动未知导入] → 全量 pytest 必须保持全绿（基线 2651 passed）；生产侧无 `import fenixd` 依赖已核实。
- [`.fenix/__init__.py` 符号链接悬空] → 任务含运行时清理步骤 `rm .fenix/__init__.py`（gitignored，非交付物）；`.fenix/` 下有 `.pytest_cache`（曾以该目录为 rootdir 跑过 pytest），悬空包标记须清除以免二次踩雷。
- [守卫硬失败在异常环境下误伤全量回归] → 断言取 basename/`hasattr` 宽松并集，且仅在「被同名包截胡」这一确定性条件下触发。
- [收敛过度回退隔离型直载导致测试互相串扰] → D3 明确只改写注释、不改加载方式；隔离职责原样保留。
- [根除后仍可能有未知的 `sys.path` 顺序依赖] → 回归锚点断言模块身份，任何残余截胡在测试层立即暴露。

## Migration Plan

主树侧 orchestrator 操作（worktree 内不可达）：
- **立项前**：删除未跟踪探针 `tests/test_import_probe2.py`（未跟踪 → 不存在于任何 worktree，实现 Agent 物理不可达）。
- **merge-back 后**：清理 `.fenix/__init__.py` 悬空符号链接（仅在根 `__init__.py` 删除后才悬空）。

worktree 交付物步骤：
1. 删除仓库根 `__init__.py`。
2. `tests/conftest.py` 加收集期守卫；新增 `tests/test_import_isolation.py`。
3. 改写 `test_config.py`、`test_spec_scheduling.py` 注释。
4. 全量 pytest 验证全绿。
5. **回滚**：`git revert` 本 change 的提交即可恢复 `__init__.py`（守卫随之会因包标记存在而报错，提示回滚不完整，需一并回滚守卫提交——单一 change 内原子回滚）。

## Open Questions

- 无。
