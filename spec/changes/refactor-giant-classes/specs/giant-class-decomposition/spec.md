# giant-class-decomposition

## ADDED Requirements

### Requirement: 三个巨型类按职责分模块

`core/worktree_manager.py` 的 `WorktreeManager`（约 4052 行 / 83 方法）、`core/pm_engine/dispatch.py` 的 `Dispatcher`（约 3856 行 / 56 方法）、`core/dashboard/server.py` 的 `DashboardHandler`（约 2300 行 / 80 方法）MUST 各自按内聚职责拆分：

- `core/worktree_manager.py` MUST 拆为 `core/worktree_manager/` 子包，按职责域（worktree 生命周期、merge-back、autostash/stash 回收、冲突消解、构建产物重建等）分子模块。
- `core/pm_engine/dispatch.py` MUST 拆为 `core/pm_engine/dispatch/` 子包，按职责域（队列与优先级、worker 执行、车道流转、交付物裁定、退避与重试等）分子模块。
- `core/dashboard/server.py` 的 `DashboardHandler` 的 **33 个 `elif` 分支路由链** MUST 按 API **资源**拆为若干子路由模块 + 一层薄分派；各资源 API handler 随其资源归入对应子模块。

每个子模块 MUST 只承载单一职责域。design 的分组表 MUST 覆盖三个类的**全部**方法，不留未归属项（未归属者 MUST 显式归组或标注「保留在宿主门面」）。

#### Scenario: 子模块职责单一

- **WHEN** 检查 worktree / dispatch 子包的任一子模块
- **THEN** 其内容为单一职责域的实现，不含其它职责域的逻辑

#### Scenario: 巨型单文件不再存在

- **WHEN** 重构完成
- **THEN** `core/worktree_manager.py`、`core/pm_engine/dispatch.py` 不再作为单文件存在，且不存在任一超过 1500 行的新子模块

#### Scenario: 路由链按资源切分

- **WHEN** 检查 `core/dashboard/server.py` 的路由分派
- **THEN** 原 33 分支 `elif` 链被拆到多个资源子路由模块，主分派仅按资源名前缀委派

### Requirement: 调用路径与测试引用零改动

既有 import 路径与属性访问 MUST 保持可用，`WorktreeManager` / `Dispatcher` / `DashboardHandler` 的导入与构造方式 MUST NOT 需要修改；允许对 import 行做最小适配。既有测试文件的引用路径 MUST NOT 需要修改。

#### Scenario: 既有 import 可用

- **WHEN** 执行 `from core.worktree_manager import WorktreeManager`、`from core.pm_engine.dispatch import Dispatcher`
- **THEN** 两者均可导入且行为不变

#### Scenario: 同名包过渡不破坏 import

- **WHEN** 把 `worktree_manager.py` 改名为 `worktree_manager/_legacy.py` 并建立包
- **THEN** 该 commit 上全部既有 import 仍可用（MUST NOT 出现「旧模块与新包同时存在的中间态」）

### Requirement: 字符串路径 patch 语义保持

模块级名字（常量、模块函数、导入名、类名）被子模块测试以字符串路径 patch 的（如 `patch("core.worktree_manager.<name>")`、`patch("core.pm_engine.dispatch.<name>")`、`patch("core.dashboard.server.<name>")`）MUST 保持 patch 语义：patch 该路径 MUST 仍能影响被测行为。design MUST 给出 patch 目标清点表与保持策略。

#### Scenario: patch 生效

- **WHEN** 对某保留下来的模块级名字执行字符串路径 patch
- **THEN** 被测调用路径读到的是 patch 后的值（与重构前一致）

### Requirement: HTTP 端点集合与行为不变

`DashboardHandler` 对外暴露的 **HTTP 端点集合（path + method）与每个端点的响应语义** MUST NOT 发生变化。重构 MUST NOT 增删端点、MUST NOT 改变状态码或响应体结构。

#### Scenario: 端点集合不变

- **WHEN** 枚举重构前后的已注册端点（path + method）
- **THEN** 两个集合完全相等

#### Scenario: 响应语义不变

- **WHEN** 用同一请求调用任一端点
- **THEN** 状态码与响应体结构与重构前一致

### Requirement: 拆分零行为变化

重构 MUST 为纯结构性搬移，MUST NOT 改变 worktree 操作语义、派发语义、路由语义或门禁阈值。发现的缺陷只记入疑点清单。

#### Scenario: 行为等价由测试佐证

- **WHEN** 运行全量 `bin/run_full_suite.py` 并与阶段 0 基线比对
- **THEN** 失败集合相对基线不新增失败

### Requirement: 不使用绝对行号锚定

任务与交付物 MUST 以方法名 / 模块名 / 资源路径锚定，MUST NOT 使用绝对行号。

#### Scenario: 任务锚点为符号名

- **WHEN** 审阅 tasks.md
- **THEN** 所有任务以符号名（方法名 / 模块名 / 路由资源）描述位置，无绝对行号
