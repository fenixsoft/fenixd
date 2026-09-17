# Proposal: refactor-facade-delegation

## Why

前三条重构（`refactor-agent-runner-module` / `refactor-dashboard-data-module` / `refactor-verification-module`）把三个巨型实现拆到了子模块，但为保持向后兼容，宿主类保留了海量「一行转发」方法，形成三层调用链。

实测（AST 全量扫描「函数体仅一条 return，且 return 的是 `self.<子对象>.<方法>(...)`、子模块函数调用或兄弟类方法调用」）：

| 宿主类 | 转发方法 / 总方法 | 转发形态 |
|---|---|---|
| `PMEngine`（`core/pm_engine/engine.py`） | **110 / 206** | `self._verification.*` 43、`self._dispatcher.*` 21、`self._family.*` 15、`self._budget.*` 10、`self._recovery.*` 7、`self._reporting.*` 3、`self._spec_integrity.*` 1、**类级静态转发到兄弟类** 10 |
| `VerificationPipeline`（`core/pm_engine/verification/pipeline.py`） | **90 / 93** | 连续整块转发到本包 9 个子模块的模块级函数（首参 `pipe` 注入） |
| `AgentRunner`（`core/agent_runner/runner.py`） | **71 / 148** | `maintenance_runs` 13、`_liveness` 12、`_provider_circuit` 11、`result_gate` 10、`_prompt_builder` 7、`_v2_server` 5、`_token_accountant` 4、其它 9 |

双份维护已实证：门面与实现签名逐参数完全一致（如 `PMEngine._enqueue` 与 `Dispatcher._enqueue` 同为 `(self, spec_name, agent_type)`）；返回注解双份（engine 92/110、pipeline 80/90、runner 66/73）。

**爆炸半径实测（关键）**：全仓转发方法调用点共 ~1910 处，其中**真正的外部生产调用点仅 35 处**（其余 82–88% 是测试）；同包兄弟模块反向穿越门面调用 467 处（如 `dispatch.py` 85 处 `pm._enqueue`）——后者违反 `refactor-verification-module` 已立的 D2b「组件 MUST NOT 回引门面私有方法」规则。

**补丁缝隙实测**：全仓**不存在**指向门面转发方法的字符串路径 patch（无 `patch("core.pm_engine.engine.X")`）。真实缝隙是对象级：测试直接对子对象赋值 Mock（`engine._verification.X = ...`）203 处、`patch.object(facade, X)` 6 处——前者与本变更正交，后者由 design 的收敛方案保证兼容。

后果有两类：

1. **签名与 docstring 双份维护**：门面方法与子模块实现各写一遍签名，改一处漏一处即漂移。
2. **阅读成本不降反升**：定位任一逻辑要跳 2–3 跳（如 `PMEngine._read_verifier_result` → `self._verification._read_verifier_result` → `report_gate.py` 模块函数）；`PMEngine` 仍是 3184 行 / 206 方法、`VerificationPipeline` 仍是 93 个方法但其中 90 个是一行转发——**巨型类没有变小，只是从「实现巨型」变成了「转发巨型」**。

## What Changes

- 收敛门面转发，消除双份签名维护与多余跳转，同时**保持调用点与 patch 语义兼容**。具体方案（`__getattr__` 统一委托 / 删除转发改直连 / 保留转发但去重签名）由 design 决策给出，逐个门面裁决。
- **不改变任何子模块实现的签名与行为**；本变更只动门面层（宿主类中可被纯粹删除或改写的转发方法体）。
- 对被子模块测试以**字符串路径 patch** 的门面方法名（若存在）MUST 保留可 patch 的解析点，MUST NOT 使既有 `patch("core.pm_engine.engine.X")` 类断言失效。
- 先补 / 复用 characterization tests 锁定门面行为的等价性。
- **不顺手修 bug**：发现的缺陷只记入疑点清单。
- 不使用绝对行号锚定。

## Capabilities

### New Capabilities

- `facade-forwarder-contract`: 门面转发层的组织契约——转发方法的收敛范围与保留边界、调用点兼容不变式、字符串路径 patch 语义保持、双份签名消除的验收口径。

### Modified Capabilities

（无——本变更不修改任何既有 spec 级行为要求）

## Impact

- **代码**：`core/pm_engine/engine.py`（3266 行）、`core/pm_engine/verification/pipeline.py`（1825 行）、`core/agent_runner/runner.py`（3803 行）的门面层。
- **API**：**潜在变化点**——若采用「删除转发改直连」，外部调用点（其余模块对 `PMEngine._X` 的调用）需随之改为直连子对象；design MUST 给出调用点迁移清单。若采用 `__getattr__` 统一委托，外部调用点零改动。此决策在 design 中裁决。
- **测试**：以字符串路径 patch 门面方法的测试须专项验证；全量 `bin/run_full_suite.py` 不引入新失败。
- **依赖（并行约束）**：本变更与前两条 spec **同文件**（`pipeline.py` / `runner.py`，且 `engine.py` 也被 `refactor-giant-classes` 波及：`PMEngine` 有 21 个转发直指 `Dispatcher`，散布在 `engine.py` 的同一区间）。故本变更 MUST 在 `refactor-giant-classes` 与 `refactor-long-functions` **都收口后才启动**（`depends_on` 已登记）。
- **运行时**：重构期间运行中的 daemon 内存持旧代码，不受影响。
