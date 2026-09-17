# Proposal: refactor-giant-classes

## Why

前三条重构（`refactor-agent-runner-module` / `refactor-dashboard-data-module` / `refactor-verification-module`）解决了三个最扎眼的巨型**文件**，但全仓仍有三个超过 2000 行的巨型**类**从未被任何重构覆盖：

- `core/worktree_manager.py` 的 `WorktreeManager` —— **4052 行 / 83 个方法**
- `core/pm_engine/dispatch.py` 的 `Dispatcher` —— **3789 行 / 55 个方法**
- `core/dashboard/server.py` 的 `DashboardHandler` —— **2300 行 / 80 个方法**（其中 `_handle_api_post` 是 **33 个 `elif` 分支**的路由链、`_handle_api` 22 个分支）

它们各自混合多个互不相关的职责（worktree 生命周期 / merge-back / autostash / 冲突消解；队列 / worker / 车道 / 交付物裁定；HTTP 路由 / 各资源 API / 静态服务），且是全仓改动最频繁的文件之一（近 300 提交内 `worktree_manager.py` 49 次、`dispatch.py` 55 次、`server.py` 65 次）——巨型单类导致新人无法整类理解、改动牵一发动全身、多 Agent 并发开发时冲突集中于此。

## What Changes

- **纯内部重构，零行为变化**：把三个巨型类按职责拆为子包 / 子模块，宿主类保留为薄门面。
  - `core/worktree_manager.py` → `core/worktree_manager/` 子包，按职责（worktree 生命周期、merge-back、autostash/stash 回收、冲突消解、dist 重建等）分子模块。
  - `core/pm_engine/dispatch.py` → `core/pm_engine/dispatch/` 子包，按职责（队列与优先级、worker 执行、车道流转、交付物裁定、退避与重试等）分子模块。
  - `core/dashboard/server.py` 的 `DashboardHandler` → 按 API **资源**把 33 分支路由链拆为若干子路由模块 + 一层薄分派；各资源 API handler 随其资源归入对应子模块。
- 采用**门面 re-export** 模式：宿主模块重新导出全部既有公开名与模块级名字，既有 import 路径与字符串路径 patch 语义保持可用。
- 拆分**先补 characterization tests**，锁定将被搬移且当前无测试覆盖的行为。
- 拆分边界以 design 的分组表为准；分组表即交付契约，MUST 覆盖全部方法，不留未归属项。
- **不顺手修 bug**：拆分中发现的缺陷只记入疑点清单，不在本变更中修改行为。

## Capabilities

### New Capabilities

- `giant-class-decomposition`: 巨型类的模块组织契约——三个巨型类的职责分组边界、子包/子模块结构、门面 re-export 兼容保证、字符串路径 patch 语义保持、既有 import 与调用路径不变式。

### Modified Capabilities

（无——本变更不修改任何既有 spec 级行为要求）

## Impact

- **代码**：`core/worktree_manager.py`（4180 行文件）→ `core/worktree_manager/` 子包；`core/pm_engine/dispatch.py`（3818 行文件）→ `core/pm_engine/dispatch/` 子包；`core/dashboard/server.py` 的 `DashboardHandler`（2300 行类）→ 按资源拆分的子路由模块 + 薄分派。
- **API**：零变化。`WorktreeManager` / `Dispatcher` / `DashboardHandler` 的导入路径与调用路径保持可用（新模块符号经宿主 re-export）。
- **测试**：全量 `bin/run_full_suite.py` 不引入新失败（须与阶段 0 基线比对）；以字符串路径 patch 的模块级名字须专项验证 patch 语义保持。
- **并发**：三条前置重构（`runner.py` / `pipeline.py` / `engine.py`）与本变更**源文件不相交**，可与 `refactor-long-functions` 并行；本变更自身覆盖三个互不 import 的文件，内部可按文件顺序推进。
- **运行时**：重构期间运行中的 daemon 内存持旧代码，不受影响。
