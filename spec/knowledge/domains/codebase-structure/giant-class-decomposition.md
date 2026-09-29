# 巨型类按职责拆分

<!-- knowledge: capability=giant-class-decomposition rev=1 sources=spec/archive/2026-09-22-refactor-giant-classes -->

`WorktreeManager`、`Dispatcher`、`DashboardHandler` 三个巨型类按内聚职责域拆为子包 / 资源子路由的组织格局与兼容不变式，宿主类保留为薄门面。

## 规则

- 拆分格局：
  - `core/worktree_manager/` 为子包，按职责域分子模块（worktree 生命周期、merge-back、autostash/stash 回收、冲突消解、构建产物重建等）；
  - `core/pm_engine/dispatch/` 为子包，按职责域分子模块（队列与优先级、worker 执行、车道流转、交付物裁定、退避与重试等）；
  - `DashboardHandler`（`core/dashboard/server.py`）的路由按 API 资源拆为若干子路由模块 + 一层薄分派，主分派仅按资源名前缀委派，各资源 API handler 随其资源归入对应子模块。
- 子模块单一职责、不超 1500 行；拆分分组表即交付契约，覆盖宿主类全部方法，不留未归属项（未归属者显式归组或标注「保留在宿主门面」）。
- 调用路径与测试引用零改动：`from core.worktree_manager import WorktreeManager`、`from core.pm_engine.dispatch import Dispatcher` 等既有导入与构造方式保持可用（允许 import 行最小适配）；新模块公开名与模块级名字经宿主模块 re-export，字符串路径 patch 语义（`patch("core.worktree_manager.<name>")` 等）保持生效；同名包过渡（`X.py` → `X/_legacy.py` 建包）不得出现旧模块与新包并存的中间态；既有测试文件的引用路径零修改。
- HTTP 端点集合（path + method）与每端点响应语义不变：不增删端点、不改状态码与响应体结构。
- 纯结构性搬移：worktree 操作语义、派发语义、路由语义、门禁阈值均不变；发现的缺陷只记疑点清单，不混入结构重构 diff；全量 `bin/run_full_suite.py` 失败集合相对阶段 0 基线不新增。
- 锚定纪律：任务与交付物以方法名 / 模块名 / 路由资源锚定，不使用绝对行号。

## 溯源

- [2026-09-22 2026-09-22-refactor-giant-classes](spec/archive/2026-09-22-refactor-giant-classes/) — 确立三大巨型类按职责拆分格局与兼容不变式：子模块职责单一、门面 re-export、import 与测试引用零改动、端点集合不变、patch 语义保持、纯结构搬移与符号名锚定
