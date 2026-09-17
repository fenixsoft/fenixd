# facade-forwarder-contract

## ADDED Requirements

### Requirement: 门面转发方法收敛

`PMEngine`（`core/pm_engine/engine.py`，约 100 个纯转发）、`VerificationPipeline`（`core/pm_engine/verification/pipeline.py`，约 90 个纯转发）、`AgentRunner`（`core/agent_runner/runner.py`，约 55 个纯转发）的一行转发方法 MUST 被收敛，以消除「门面签名与子模块实现双份维护」与多余的调用跳转。

「纯转发方法」判据：函数体仅一条 `return`，且返回值为 `self.<子对象>.<方法>(...)` 或子模块函数的直接调用。

收敛后：门面 MUST NOT 再存在与子模块实现重复书写的完整签名 + docstring 的转发方法（若保留转发，MUST 采用不重复签名的机制）；design MUST 给出收敛方案（`__getattr__` 统一委托 / 删除转发改直连 / 保留转发去重签名）与逐门面裁决。

#### Scenario: 转发方法被消除或去重

- **WHEN** 对收敛后的三个宿主类重新执行「纯转发方法」AST 识别
- **THEN** 剩余转发方法数量为 0，或剩余者均以不重复签名的方式（如 `__getattr__` 委托）实现

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

任务与交付物 MUST 以方法名 / 类名锚定，MUST NOT 使用绝对行号。

#### Scenario: 任务锚点为符号名

- **WHEN** 审阅 tasks.md
- **THEN** 所有任务以方法名 / 类名描述位置，无绝对行号
