# 门面转发收敛契约

<!-- knowledge: capability=facade-forwarder-contract rev=1 sources=spec/archive/2026-09-22-refactor-facade-delegation -->

约束 `PMEngine`（`core/pm_engine/engine.py`）、`VerificationPipeline`（`core/pm_engine/verification/pipeline.py`）、`AgentRunner`（`core/agent_runner/runner.py`）三大门面类转发方法的收敛范围与保留边界，消除「门面签名与子模块实现双份维护」与多余调用跳转。

## 规则

- 门面不得保留与子模块实现重复书写完整签名 + docstring 的一行转发方法；保留的转发必须以不重复签名的机制实现——`__getattr__` 统一委托，或类级别名 `name = staticmethod(目标)`（别名无签名无 docstring）。
- 「纯转发方法」判据：函数体仅一条 `return`（允许前置 docstring），且返回值为子对象方法调用、同门面内转发、本仓子模块模块级函数直接调用、兄弟类静态方法直接调用之一。向 stdlib / 第三方模块的调用（如 `time.monotonic()`、`re.sub(...)`）不计入判据——不构成双份签名，保留为显式方法。
- 静态方法式转发（首参非 `self`/`pipe`）不得以「删除 + 实例 `__getattr__`」方式收敛：`Cls.<名>(...)` 类直调不经实例 `__getattr__`，删除即 `AttributeError`，必须以类级别名或等价机制同时保留 `Cls.<名>` 与 `self.<名>` 两条解析路径；实例式转发经 `__getattr__` 委托时，不得对无 `self` 首参的目标函数注入 `self`（不走 `functools.partial(func, self)` 路径）。
- 调用路径兼容：采用「删除转发改直连」时必须给出完整调用点迁移清单（全仓 `self.X(...)` / `obj.X(...)` 改点），迁移后无一处残留对已删除门面方法的调用；采用 `__getattr__` 统一委托时外部调用点零修改。既有 import 路径（如 `from core.pm_engine.engine import PMEngine`）保持可导入。
- 字符串路径 patch 语义保持：被子模块测试以字符串路径 patch（`patch("core.pm_engine.engine.<name>")` 等）的门面方法名必须保持 patch 语义，调用方读到 patch 后的行为，不得使既有 patch 断言静默失效。
- 零行为变化：子模块实现的签名与行为不变；门面方法返回值的可观测内容不变；任一被收敛方法的签名与 docstring 在仓库中只存在一处（子模块实现处）。
- 锚定纪律：任务与交付物以方法名 / 类名锚定，`文件:行` 只可作佐证，不得以绝对行号作为唯一锚点。

## 溯源

- 2026-09-22 2026-09-22-refactor-facade-delegation — 确立三大门面纯转发方法收敛契约：纯转发判据与 stdlib 例外、静态式转发的类级别名保留边界、调用点与 patch 语义兼容、双份签名消除的验收口径
