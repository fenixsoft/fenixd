# 数据读取模块化

<!-- knowledge: capability=dashboard-data-modules rev=1
     sources=spec/archive/2026-09-21-refactor-dashboard-data-module -->

dashboard 数据聚合层的模块组织契约：职责子模块 + 门面 re-export，两条 import 路径与测试 patch 语义保持不变。

## 规则

- `core/dashboard/data.py` 组织为 `core/dashboard/data/` 包，按职责域拆为独立子模块（`admin_alerts`、`admin_actions`、`spec_archive`、`spec_docs`、`tasks`、`log_index`、`artifacts`、`runs`、`timeline`、`summary`、`config_admin`、`evolution_items`、`state` 等）；每子模块只承载单一职责域的顶层函数，不出现跨域混杂；不存在巨型单文件 `data.py`，也不存在超过 1500 行的子模块。
- 门面 `data/__init__.py` 显式逐条 re-export 全部既有公开名（MUST NOT 使用星号导入），导出范围覆盖四类名字：函数、类、模块级常量、导入进来被二次导出的名字（`_is_running`、`USER_CONFIG_PATH`），并含下划线私有别名（`_parse_run_task_done`、`_find_impl_run_file`）；`from core.dashboard import data` 与 `from core.dashboard.data import <name>` 两条调用路径均可用，外部消费点（server、pm_engine、fenixd、bin 入口及全部测试）零修改。
- patch 语义保持：对模块级名字的 `patch("core.dashboard.data.<name>")` 在重构后仍对使用该名字的函数生效——实现方式为被搬移函数体内经门面延迟解析（`import core.dashboard.data as _facade` 后以 `_facade.<name>` 取值），MUST NOT 依赖门面 re-export 本身（那只是值拷贝）。
- 建包顺序契约：先把旧实现整体改名入包为过渡模块 `_legacy.py`、由门面显式 re-export，再分阶段把各组摘出到子模块，过渡模块在内容全部迁出后的收尾阶段删除；MUST NOT 先建空包再原地搬移（同名包会遮蔽同名模块，使未搬移函数短暂不可达）。
- 零行为变化：拆分为纯结构性搬移，不改变任何函数的输入输出、异常语义或副作用；搬移中发现的缺陷只记入疑点清单，不顺手修复。
- 分阶段提交：搬移按模块间依赖度从叶子到中枢分阶段进行，每阶段以独立 commit 收尾且该 commit 前通过全量 pytest 与 import 路径校验，可独立回滚。
- 任务与交付物声明以函数名、模块名或 import 路径锚定，MUST NOT 使用绝对行号。

## 溯源

- [2026-09-21 2026-09-21-refactor-dashboard-data-module](spec/archive/2026-09-21-refactor-dashboard-data-module/) — 5297 行 data.py（150 个顶层名、9 类混杂职责、全仓被 import 最多）拆为职责子模块 + 薄门面，固化门面 re-export、patch 延迟解析、先改名入包与分层分阶段提交契约
