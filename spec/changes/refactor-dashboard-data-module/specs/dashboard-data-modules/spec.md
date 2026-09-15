# dashboard-data-modules

## ADDED Requirements

### Requirement: dashboard 数据层按职责分模块

`core/dashboard/data.py` MUST 重构为 `core/dashboard/data/` 包，按职责拆分为独立子模块：`admin_alerts`、`admin_actions`、`spec_archive`、`spec_docs`、`tasks`、`log_index`、`artifacts`、`runs`、`timeline`、`summary`、`config_admin`、`evolution_items`、`state`。每个子模块 MUST 只承载单一职责域的顶层函数，MUST NOT 出现跨域混杂。

#### Scenario: 子模块职责单一

- **WHEN** 检查 `core/dashboard/data/` 下任一子模块
- **THEN** 其顶层函数全部属于同一职责域（如 `runs.py` 只含 run 记录/事件/成本，不含告警或配置函数）

#### Scenario: 巨型单文件不再存在

- **WHEN** 重构完成
- **THEN** `core/dashboard/data.py` 文件不存在，且不存在任何一个超过 1500 行的 `core/dashboard/data/` 子模块

### Requirement: 门面 re-export 保持调用路径零改动

`core/dashboard/data/__init__.py` MUST 作为门面重新导出全部既有公开名，以及既有的下划线私有别名（至少含 `_parse_run_task_done`、`_find_impl_run_file`）。`from core.dashboard import data` 与 `from core.dashboard.data import <name>` 两条既有调用路径 MUST 保持可用，外部消费点（约 227 处，含 `core/dashboard/server.py`、`core/pm_engine/engine.py`、`core/pm_engine/verification.py`、`fenixd.py`、`bin/fenix_dashboard.py`、`bin/fenix_process.py`）MUST NOT 需要任何修改。

门面 MUST 显式逐条 re-export（MUST NOT 使用 `from ._legacy import *` 之类的星号导入），导出范围 MUST 覆盖四类既有名字：函数、类、模块级常量、以及**导入进来被二次导出的名字**（`_is_running`、`USER_CONFIG_PATH`）。判定清单 MUST 由静态清点落盘（`contract-inventory.md`）并与分组表对齐，MUST NOT 仅以「AST 顶层 `def` 扫描」为准。

#### Scenario: 两条 import 路径均可用

- **WHEN** 执行 `from core.dashboard import data` 与 `from core.dashboard.data import parse_state`
- **THEN** 两者均成功，且 `data.parse_state is parse_state` 为真

#### Scenario: 私有别名可访问

- **WHEN** 访问 `core.dashboard.data._parse_run_task_done` 与 `._find_impl_run_file`
- **THEN** 均返回可调用对象，与拆分前所指向的实现一致

#### Scenario: 模块级常量与导入别名可访问

- **WHEN** 访问 `core.dashboard.data.USER_CONFIG_PATH` 与 `core.dashboard.data._is_running`
- **THEN** 两者均可解析，且与拆分前语义一致（前者为 `Path`，后者可调用）

#### Scenario: 消费点零修改

- **WHEN** 重构完成后运行全量 pytest
- **THEN** 不产生任何因 import 路径或属性名变更导致的收集错误或失败

### Requirement: 门面 re-export MUST 保持模块级名字的 patch 语义

对模块级名字的 `unittest.mock.patch("core.dashboard.data.<name>")` MUST 在重构后仍对使用该名字的函数生效。因门面的 `from .<mod> import <name>` 只是值拷贝，MUST 采用「调用点经门面延迟解析」实现（被搬移函数体内 `import core.dashboard.data as _facade` 后以 `_facade.<name>` 取值），MUST NOT 依赖门面 re-export 本身保持 patch 语义。

适用范围至少含既有测试已 patch 的两个名字：`_is_running`（`daemon_health` 使用）、`USER_CONFIG_PATH`（配置读取路径使用）。

#### Scenario: patch 后调用点观察到替身

- **WHEN** 在重构后执行 `patch("core.dashboard.data._is_running", return_value=True)` 并调用 `core.dashboard.data.daemon_health(root)`
- **THEN** 返回值由替身决定（`"running"`），未被真实 `is_running` 覆盖

#### Scenario: 配置路径隔离仍有效

- **WHEN** 执行 `patch("core.dashboard.data.USER_CONFIG_PATH", tmp_path/"config.yaml")` 并调用 `read_effective_config(...)`
- **THEN** 读取的是被 patch 的路径，而非真实 `~/.fenix/config.yaml`

### Requirement: 建包 MUST 先改名入包，不得使旧实现短暂不可达

因 Python 解析同名「包」优先于「模块」，`core/dashboard/data/__init__.py` 一旦存在，`core/dashboard/data.py` 即不可达。搬移 MUST 先把旧实现整体改名为包内过渡模块（`core/dashboard/data/_legacy.py`），由门面显式 re-export 其全部名字，再分阶段把各组摘出到子模块；过渡模块 MUST 在其内容全部迁出后的收尾阶段删除。MUST NOT 先建立空包再原地搬移。

#### Scenario: 中间阶段仍全绿

- **WHEN** 任一中间阶段 commit 后运行全量 pytest
- **THEN** 尚未搬移的函数仍可经门面访问，失败集合与重构前基线一致

#### Scenario: 过渡模块最终清除

- **WHEN** 重构完成
- **THEN** `core/dashboard/data/_legacy.py` 不存在，且门面不残留对它的 import

#### Scenario: 两条 import 路径均可用

- **WHEN** 执行 `from core.dashboard import data` 与 `from core.dashboard.data import parse_state`
- **THEN** 两者均成功，且 `data.parse_state is parse_state` 为真

#### Scenario: 私有别名可访问

- **WHEN** 访问 `core.dashboard.data._parse_run_task_done` 与 `._find_impl_run_file`
- **THEN** 均返回可调用对象，与拆分前所指向的实现一致

#### Scenario: 消费点零修改

- **WHEN** 重构完成后运行全量 pytest
- **THEN** 不产生任何因 import 路径或属性名变更导致的收集错误或失败

### Requirement: 拆分零行为变化

重构 MUST 为纯结构性搬移，MUST NOT 改变任何函数的输入输出行为、异常语义或副作用。搬移过程中发现的缺陷 MUST 只记入疑点清单，MUST NOT 顺手修复。

#### Scenario: 全量测试不引入新失败

- **WHEN** 重构完成后运行 `bin/run_full_suite.py`
- **THEN** 失败集合相对重构前基线不新增任何失败

#### Scenario: 发现的问题只记录

- **WHEN** 搬移某函数时发现一个既有缺陷
- **THEN** 该缺陷被写入疑点清单文件，相关代码行为保持不变

### Requirement: 搬移按依赖分层分阶段提交

搬移 MUST 按模块间依赖度从叶子到中枢分阶段进行，每个阶段 MUST 以独立 commit 收尾，且该 commit 前 MUST 通过全量 pytest 与 import 路径校验。

#### Scenario: 每阶段可独立回滚

- **WHEN** 某阶段提交后发现回归
- **THEN** 可仅回退该阶段 commit，前序阶段成果保持可用

### Requirement: 不使用绝对行号锚定

本变更的任务描述与交付物声明 MUST 以函数名、模块名或 import 路径锚定，MUST NOT 使用绝对行号，以保证后续会继续修改这些文件的其它变更不会使本变更的任务描述失真。

#### Scenario: 任务锚点为符号名

- **WHEN** 审阅 tasks.md
- **THEN** 每个任务以函数名/模块名/路径描述目标，不出现「第 N 行」式锚点
