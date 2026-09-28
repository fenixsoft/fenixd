# 门面转发契约

<!-- knowledge: capability=facade-forwarder-contract rev=2 sources=spec/archive/2026-09-22-refactor-facade-delegation,spec/archive/2026-09-29-evo-fix-pm-facade-drift-forwarder-contract -->

约束 `PMEngine`（`core/pm_engine/engine.py`）、`AgentRunner`（`core/agent_runner/runner.py`）、`VerificationPipeline`（`core/pm_engine/verification/pipeline.py`）三大门面类的转发机制：转发以 `__getattr__` + 类级显式注册表统一委托，门面不保留重复签名的一行转发方法；core/ 下全部门面字面调用点必须可经门面解析，由契约测试硬门守护。

## 规则

- 收敛边界：门面不得保留与子模块实现重复书写完整签名 + docstring 的一行转发方法；保留的转发必须以不重复签名的机制实现——`__getattr__` 统一委托（未命中名严格 `raise AttributeError`，dunder 一律不转发），或类级别名 `name = staticmethod(目标)`（别名无签名无 docstring）。
- 「纯转发方法」判据：函数体仅一条 `return`（允许前置 docstring），且返回值为子对象方法调用、同门面内转发、本仓子模块模块级函数直接调用、兄弟类静态方法直接调用之一。向 stdlib / 第三方模块的调用（如 `time.monotonic()`、`re.sub(...)`）不计入判据——不构成双份签名，保留为显式方法。
- 静态方法式转发（首参非 `self`/`pipe`）不得进入实例注册表：`Cls.<名>(...)` 类直调不经实例 `__getattr__`，此类名字以类级别名或等价机制同时保留 `Cls.<名>` 与 `self.<名>` 两条解析路径，并以显式豁免名单管理（名单变更须附注释理由）；实例式转发经 `__getattr__` 委托时，不得对无 `self` 首参的目标函数注入 `self`（不走 `functools.partial(func, self)` 路径）。
- 调用路径兼容：采用「删除转发改直连」时必须给出完整调用点迁移清单（全仓 `self.X(...)` / `obj.X(...)` 改点），迁移后无一处残留对已删除门面方法的调用；采用 `__getattr__` 统一委托时外部调用点零修改。既有 import 路径（如 `from core.pm_engine.engine import PMEngine`）保持可导入。
- 字符串路径 patch 语义保持：被子模块测试以字符串路径 patch（`patch("core.pm_engine.engine.<name>")` 等）的门面方法名必须保持 patch 语义，调用方读到 patch 后的行为，不得使既有 patch 断言静默失效。
- 零行为变化：子模块实现的签名与行为不变；门面方法返回值的可观测内容不变；任一被收敛方法的签名与 docstring 在仓库中只存在一处（子模块实现处）。
- 调用点覆盖硬门：core/ 下全部 `self._pm.<名>` 字面属性调用点必须可经其所属门面解析。解析域 = 注册表键 ∪ 门面显式定义（`dir(cls)` 覆盖 MRO 混入方法、类属性与惰性 property；方法体内 `self.<名> = ...` 实例属性赋值按 MRO 源码 AST 推导），dunder 与测试/注释不计。任一调用点不可解析即契约测试失败，失败信息必须含缺失名字与调用文件:行号，并按「注册表/显式/豁免」三归属可辨。
- 扫描域目录分桶：调用点按目录分桶归各自门面检查——`core/pm_engine/**` 的 `self._pm` 回引对 PMEngine 解析，`core/agent_runner/**` 的对 AgentRunner 解析；未入任何桶的目录出现 `self._pm` 调用点即测试失败，分桶必须完备。VerificationPipeline 侧禁止 `self._pm` 私有回引，只做注册表反向断言。
- 注册表反向断言（无悬空条目）：每张注册表条目的目标必须可在其门面上解析，断言按条目形态适配——PMEngine 二元组 `(子对象属性, 方法)` 经惰性 property + `getattr` 链解析；AgentRunner 二元组与模块函数两种形态并存，分别解析；VerificationPipeline 单值模块函数直接解析。断言对象是「条目可解析」，不做「键从未被调用」的死键检查——仅供动态/外部调用的键合法存在。
- 漏注册是错误，不是软失败：调用点不得以 try/except 或 `getattr` 默认值兜底吞掉漏注册；未注册名经 `__getattr__` 严格抛 AttributeError，由契约测试在合入前拦截。可选能力探测语义（`getattr(self._pm, "<名>", default)` 带默认值形态、fail-soft try/except 子对象探测）不属硬契约调用点，不入扫描面，但必须在契约测试中显式豁免并注明理由。
- 锚定纪律：任务与交付物以方法名 / 类名锚定，`文件:行` 只可作佐证，不得以绝对行号作为唯一锚点。

## 关键行为

- 契约测试（`tests/test_pm_facade_forwarder_contract.py`）双向守护：正扫 AST 断言分桶调用点全部可解析且全部分桶；反向逐表断言注册表条目可解析，另断言 verification 侧零 `self._pm` 回引、合法不入表名字不误报。
- 惰性 property（如 `_dispatcher`）在反向断言中经真实构造解析，保证条目指向的子对象方法真实存在。

## 溯源

- 2026-09-22 2026-09-22-refactor-facade-delegation — 确立三大门面纯转发方法收敛契约：纯转发判据与 stdlib 例外、静态式转发的类级别名保留边界、调用点与 patch 语义兼容、双份签名消除的验收口径
- 2026-09-29 2026-09-29-evo-fix-pm-facade-drift-forwarder-contract — 登记漂移预分类转发条目（`_preclassify_drift → ("_dispatcher", "_preclassify_drift")`，修复该调用点运行时 AttributeError 整轮回滚）；新增门面调用点覆盖性契约硬门（AST 正扫 + 目录分桶 + 悬空反向断言 + 显式豁免），三张同构注册表同门守护
