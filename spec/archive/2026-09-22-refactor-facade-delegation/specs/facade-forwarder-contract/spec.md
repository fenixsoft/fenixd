# facade-forwarder-contract

## ADDED Requirements

### Requirement: 门面转发方法收敛

`PMEngine`（`core/pm_engine/engine.py`，约 110 个纯转发）、`VerificationPipeline`（`core/pm_engine/verification/pipeline.py`，约 90 个纯转发）、`AgentRunner`（`core/agent_runner/runner.py`，约 65 个纯转发）的一行转发方法 MUST 被收敛，以消除「门面签名与子模块实现双份维护」与多余的调用跳转。

「纯转发方法」判据：函数体仅一条 `return`（允许前置 docstring），且返回值为以下之一——`self.<子对象>.<方法>(...)`、`self.<方法>(...)`（同门面内转发）、本仓子模块的模块级函数直接调用、兄弟类的静态方法直接调用。向 stdlib / 第三方模块的调用（如 `AgentRunner._now` 的 `return time.monotonic()`、`AgentRunner._normalize_run_id` 的 `return re.sub(...)`）**不计入**本判据：它们不是任何子模块实现的转发，不构成双份签名，MUST 保留为显式方法（design D3）。

收敛后：门面 MUST NOT 再存在与子模块实现重复书写的完整签名 + docstring 的转发方法（若保留转发，MUST 采用不重复签名的机制，如 `__getattr__` 委托或**类级别名** `name = staticmethod(目标)`——别名无签名无 docstring）；design MUST 给出收敛方案（`__getattr__` 统一委托 / 删除转发改直连 / 保留转发去重签名）与逐门面裁决。

**静态方法式转发的保留边界**：首参不是 `self`/`pipe` 的 `@staticmethod` 式转发（收敛对象中的 `PMEngine` 10 个、`AgentRunner` 12 个、`VerificationPipeline` 5 个，合计 27 个）MUST NOT 以「删除 + 实例 `__getattr__`」方式收敛——`Cls.<名>(...)` 式类直调不经实例 `__getattr__`，删除即 `AttributeError`；MUST 以类级别名或等价机制同时保留 `Cls.<名>` 与 `self.<名>` 两条解析路径。反之，首参为 `self`/`pipe` 的实例式转发经 `__getattr__` 委托时 MUST NOT 对无 `self` 首参的目标函数注入 `self`。

#### Scenario: 转发方法被消除或去重

- **WHEN** 对收敛后的三个宿主类重新执行「纯转发方法」AST 识别
- **THEN** 剩余转发方法数量为 0，或剩余者均以不重复签名的方式（如 `__getattr__` 委托、类级别名）实现；MUST NOT 残留重复书写完整签名 + docstring 的转发方法体

#### Scenario: 静态方法式转发的类直调仍可用

- **WHEN** 对任一首参非 `self`/`pipe` 的原 `@staticmethod` 式转发名执行类直调（如 `core/pm_engine/engine.py` 中 `VerificationPipeline._normalize_fail_signature(text)`、`core/agent_runner/runner.py` 中 `AgentRunner._entry_is_tool_result(entry)`）
- **THEN** 该名仍是类属性，调用返回与重构前一致的结果

#### Scenario: 实例路径调用参数不被二次注入

- **WHEN** 门面内以实例路径调用原静态式转发（如 `pipeline.py` 中 `self._extract_replan_error_items(env_error)`）
- **THEN** 实参不因委托机制被追加 `self`（即该名 MUST NOT 走 `functools.partial(func, self)` 路径）

#### Scenario: 双份签名不再存在

- **WHEN** 检查任一被收敛的方法
- **THEN** 其签名与 docstring 在仓库中只存在一处（子模块实现处）

### Requirement: 调用路径兼容

收敛 MUST 保持既有调用点可用。若采用「删除转发改直连」，design MUST 给出**完整的调用点迁移清单**（全仓 `self.X(...)` / `obj.X(...)` 的改点），迁移后 MUST NOT 残留对已删除门面方法的调用。若采用 `__getattr__` 统一委托，外部调用点 MUST 零修改。

#### Scenario: 调用点无残留断链

- **WHEN** 全仓搜索被删除的门面方法名
- **THEN** 无任何调用点仍引用它（全部已迁移或经委托可达）

#### Scenario: 导入路径不变

- **WHEN** 执行 `from core.pm_engine.engine import PMEngine` 等既有 import
- **THEN** 均可导入

#### Scenario: 类直调调用点不残留断链

- **WHEN** 全仓搜索 `Cls.<原名>(...)` 式类直调（`Cls ∈ {PMEngine, VerificationPipeline, AgentRunner}`）
- **THEN** 全部仍可解析（经类属性或类级别名），无一处因收敛而 `AttributeError`

### Requirement: 字符串路径 patch 语义保持

若某被收敛的门面方法名被子模块测试以字符串路径 patch（如 `patch("core.pm_engine.engine.<name>")`），该 patch MUST 保持语义；MUST NOT 因收敛而使既有 patch 断言静默失效。design MUST 给出 patch 目标清点与保持策略。

#### Scenario: patch 生效

- **WHEN** 对某门面方法名执行字符串路径 patch
- **THEN** 调用方读到的是 patch 后的行为（与重构前一致）

### Requirement: 零行为变化

收敛 MUST NOT 改变任何子模块实现的签名与行为；MUST NOT 改变门面方法返回值的可观测内容。

#### Scenario: 返回值不变

- **WHEN** 对同一输入调用任一曾被转发的门面方法
- **THEN** 返回值与重构前一致

#### Scenario: 全量测试不引入新失败

- **WHEN** 运行全量 `bin/run_full_suite.py`
- **THEN** 失败集合相对基线不新增失败

### Requirement: 不使用绝对行号锚定

任务与交付物 MUST 以方法名 / 类名锚定，MUST NOT 仅以绝对行号定位。证据性引用 MAY 附 `文件:行` 作佐证，但 MUST 同时给出符号名（方法名 / 类名）——行号会随并行 SPEC（`refactor-long-functions` 等）落地而漂移，符号名才是指认依据。

#### Scenario: 任务锚点为符号名

- **WHEN** 审阅 tasks.md
- **THEN** 每项任务的定位方式为方法名 / 类名（长度区间或纯行号 MUST NOT 作为唯一锚点）
