# Proposal: refactor-dashboard-data-module

## Why

`core/dashboard/data.py` 已达 5297 行、114 个顶层函数 + 4 个类 + 32 个模块级常量/别名（共 150 个顶层名），混居至少 9 类互不相关的职责（Administrator 告警、admin 写操作、SPEC 文档读取、tasks 解析、日志块索引、验证产物解析、run 记录与成本核算、时间轴重建、**以及一整块与 dashboard 无关的配置读写引擎**）。它是全仓被 import 最多的模块（277 条引用行 / 45 个消费文件，其中 38 个为测试文件），也是近 200 提交中改动最频繁的文件（137 次）。巨型单文件导致：新功能无明确归属、改动牵一发动全身、多 Agent 并发开发时冲突集中于此、新人无法整文件理解。

## What Changes

- **纯内部重构，零行为变化**：把 `core/dashboard/data.py` 按职责拆为 `core/dashboard/data/` 包（13 个职责子模块 + 一个薄门面 `__init__.py`）。
- 采用**门面 re-export** 模式：`core/dashboard/data/__init__.py` 重新导出全部既有公开名（含 `_parse_run_task_done` / `_find_impl_run_file` 等下划线别名、模块级常量、以及 `_is_running` / `USER_CONFIG_PATH` 这类导入后二次导出的名字），`from core.dashboard import data` 与 `from core.dashboard.data import parse_state` 两条既有调用路径**完全不变**（277 条引用行 / 45 个消费文件零修改）。
- 搬移采用**先改名入包再逐组摘出**（`data.py` → `data/_legacy.py`，门面显式 re-export），因同名包会遮蔽同名模块，先建空包会使未搬移函数短暂不可达（见 design D7）。
- 对既有测试以 `patch("core.dashboard.data.<name>")` 替换的模块级名字（`_is_running`、`USER_CONFIG_PATH`），调用点经门面延迟解析以保持 patch 语义（见 design D8）。
- 拆分**先补 characterization tests**：对将被搬移且当前无测试覆盖的函数锁定行为。
- **不顺手修 bug**：拆分中发现的缺陷只记录清单，不改行为。
- 拆分边界以 design 的分组表为准；分组表即交付契约，且 MUST 覆盖全部四类顶层名字（函数、类、模块级常量、导入别名），不留未归属项。

## Capabilities

### New Capabilities

- `dashboard-data-modules`: dashboard 数据聚合层的模块组织契约——包结构、子模块职责边界、门面 re-export 兼容保证、测试调用路径不变式。

### Modified Capabilities

（无——本变更不修改任何既有 spec 级行为要求）

## Impact

- **代码**：`core/dashboard/data.py`（5297 行单文件）→ `core/dashboard/data/` 包（13 子模块 + `__init__.py`）；`core/dashboard/data.py` 删除（搬移期先改名为 `data/_legacy.py` 过渡，收尾删除）。
- **API**：零变化。`core/dashboard/server.py`、`core/pm_engine/engine.py`、`core/pm_engine/verification.py`、`fenixd.py`、`bin/fenix_dashboard.py`、`bin/fenix_process.py` 及全部测试文件的 import 与属性访问路径保持可用。
- **测试**：38 个测试文件（共 45 个消费文件中）引用 `core.dashboard.data`，全部零修改——其中 `patch("core.dashboard.data._is_running")`（`tests/test_config.py` 8 处）与 `patch("core.dashboard.data.USER_CONFIG_PATH")`（`tests/test_dashboard_data.py` 3 处）两处 patch 语义由 design D8 的「调用点经门面延迟解析」保证；新增 characterization tests 独立提交。验收标准为全量 pytest **不引入新失败**（须与阶段 0 记录的基线失败集合比对，且 patch 语义单列专项验证）。
- **运行时**：重构期间运行中的 daemon 内存持旧代码，不受影响。
