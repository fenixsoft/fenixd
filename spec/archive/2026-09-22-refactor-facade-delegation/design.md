# Design: refactor-facade-delegation

## Context

前三条重构把三个巨型实现拆到子模块，宿主类保留了海量一行转发方法，形成三层调用链。AST 全量扫描（判据：函数体仅一条 `return`，返回 `self.<子对象>.<方法>(...)`、子模块函数调用或兄弟类方法调用）：

| 宿主类 | 转发 / 总方法 | 形态 |
|---|---|---|
| `PMEngine`（`engine.py`） | **110 / 206** | `_verification` 43、`_dispatcher` 21、`_family` 15、`_budget` 10、`_recovery` 7、`_reporting` 3、`_spec_integrity` 1、**类级静态转发到兄弟类** 10 |
| `VerificationPipeline`（`verification/pipeline.py`） | **90 / 93** | 85 个连续整块转发到本包 9 子模块的模块级函数（首参 `pipe`，如 `_read_verify_report` → `report_gate._read_verify_report`）+ **5 个 `@staticmethod` 式**（`_extract_replan_error_items` / `_replan_errors_unconsumed` / `_normalize_fail_signature` / `_load_frozen_scenarios` / `_port_responds`） |
| `AgentRunner`（`runner.py`） | **65 / 148** | `_liveness` 12、`_provider_circuit` 11、`_prompt_builder` 7、`_v2_server` 5、`_token_accountant` 4、`self` 首参模块函数 13（`maintenance_runs` / `result_gate` 族）、**`@staticmethod` 式（首参非 `self`）13** |

**判据与计数口径**：函数体为单条 `return`（允许前置 docstring）的「调用形态」。三个门面合计 **265** 个（`PMEngine` 110 + `VerificationPipeline` 90 + `AgentRunner` 65）；其中 2 个是**向 stdlib 的调用**（`AgentRunner._now` = `return time.monotonic()`、`_normalize_run_id` = `return re.sub(...)`）——不是任何子模块实现的转发，不构成双份签名，MUST 保留为显式方法（design D3），**不计入收敛对象**。故**收敛对象 263 个**。**逐名权威清单以阶段 0 落盘的 `facade-inventory.md` 为准**（本表与之不符时以清单为准）。

**形态二分（决定实现方式，见 D7）**——按「首参是否为 `self`/`pipe`」二分，统计范围为上述 263 个收敛对象：

| 门面 | 实例式（首参 `self`/`pipe`） | **静态式（首参非 `self`，`@staticmethod`）** |
|---|---|---|
| `PMEngine` | 100 | **10** |
| `VerificationPipeline` | 85 | **5** |
| `AgentRunner` | 51 | **12** |

静态式合计 **27** 个（`AgentRunner` 的 `_normalize_run_id` 因目标是 stdlib `re.sub` 而保留为真方法，不计入），MUST 单独收敛（不能走实例 `__getattr__`，见 D1 约束 4 / D7）。

**关键实测（决定方案选择）：**

- **字符串路径 patch：零命中**。全仓**不存在** `patch("core.pm_engine.engine.X")` / `patch("...pipeline.X")` / `patch("...runner.X")` 指向任何转发方法。唯一模块字符串 patch 是 `core.agent_runner.runner.time.time/sleep`（stdlib 属性，与转发无关）。
- **对象级缝隙**：`patch.object(facade, X)` 6 处（多为 `_send_human_escalation_alert`、`_sibling_*`、`_run_agent_worker`）；测试直接对**子对象**赋值 Mock（`engine._verification.X = ...`）**203 处**——后者与门面方案正交。
- **爆炸半径**：转发方法调用点共 ~1910 处，其中**真外部生产调用点仅 35 处**，82–88% 是测试；同包兄弟模块反向穿越门面 467 处（`dispatch.py` 85 处 `pm._enqueue` 等）。
- **行区间重叠（证据性引用，符号锚点为 `_read_verify_report`…`_clear_fail_history` 转发块 vs `_run_*` 长函数族）**：`pipeline.py` 转发块与长函数块**零重叠**；`runner.py` 转发三簇（`run_administrator`/`run_self_review`/`run_evolution` 族、`_entry_is_tool_result`、`_build_prompt`…`_extract_usage_info` 族）与 `_execute_agent_inner` **零重叠**。

## Goals / Non-Goals

**Goals:**

- 消除门面与子模块实现的**双份签名 / docstring 维护**。
- 让宿主类**真正变小**（删掉 263 个转发方法体；其中 27 个静态式转为类级别名；另 2 个 stdlib 调用形态保留），而非「从实现巨型变成转发巨型」。
- **零调用点破坏、零 patch 语义破坏**。

**Non-Goals:**

- 不改变任何子模块实现的签名与行为。
- 不修改同包兄弟模块对门面的调用（那是 `refactor-verification-module` D2b 的范畴；本变更只裁决门面）。
- 不修 bug。

## Decisions

### D1：采用「`__getattr__` 统一委托」（方案 A）

三个宿主类各自实现 `__getattr__`，把未命中的属性按**显式注册表**转发到对应子对象 / 子模块函数；删除全部纯转发方法体。

**选型对比（已实测）：**

| | A `__getattr__` 统一委托 | B 删除转发、调用方直连 | C 保留转发 + 装饰器去重签名 |
|---|---|---|---|
| 调用点破坏 | **0 处** | ~1,760 处改写（含测试 1,134） | 0 处 |
| `patch.object(facade, X)` 6 处 | **兼容**（mock 写实例 `__dict__`，天然遮蔽 `__getattr__`；退出删属性即恢复转发） | **必碎**，须改指子对象 | 兼容 |
| 子对象赋值 203 处 | 不受影响 | 不受影响 | 不受影响 |
| 双份签名消除 | **彻底**（不再写签名） | 彻底 | 消除漂移（`functools.wraps` 式复制 `__doc__`/`__annotations__`），但转发壳仍占行数 |
| 宿主类真正变小 | **是**（删 263 个方法体，约 1,300 行；静态式 27 个转为一行别名） | 是 | **否**（转发壳保留） |
| 风险 | 隐式行为、`dir()`/`hasattr()` 语义 | 工作面最大、易引入行为变化、且与 `refactor-giant-classes`（拆 dispatch.py，内含大量穿越调用）规格耦合 | 不解决阅读成本 |

**裁决：A。** 理由：在「零调用点破坏」这一本项目最硬的风险约束下，A 与 C 并列最优；而 C 不解决「宿主类没变小」这一本 spec 的核心目标；B 虽最彻底，但 1,760 处改写（尤其 1,134 处测试）引入的行为变化风险与本项目「零行为变化」红线冲突，且与 `refactor-giant-classes` 形成规格耦合。A 以「显式注册表」换取零调用点改动，且注册表本身是比 90 个一行方法**更集中**的单一事实源。

**`__getattr__` 实现约束：**

1. 对 `__` 开头 / `__` 结尾的 dunder 名 MUST NOT 转发（避免破坏 pickle/copy/`isinstance` 协议）——直接 `raise AttributeError`。
2. 名字不在注册表时 MUST `raise AttributeError`（使 `hasattr`/`getattr(...,default)` 语义正确，MUST NOT 恒真）。
3. 三个类的注册表 MUST 覆盖全部原转发方法名，逐名可核对；注册表由契约测试锁定（D4）。
4. **类级静态转发的通用规则（三类皆适用，不限于 `PMEngine`）**：首参不是 `self`/`pipe` 的 `@staticmethod` 式转发（`PMEngine` 10、`AgentRunner` 12、`VerificationPipeline` 5，见上「形态二分」表）不适用实例 `__getattr__` 的**类属性访问路径**——`Cls.<名>(...)` 式类直调不经实例 `__getattr__`，删除即 `AttributeError`；经实例调用（`self.<名>(...)`）虽可被 `__getattr__` 覆盖，但 `partial(func, self)` 形态对无 `self` 首参的函数是错的（多注一个 `self` 直接 `TypeError`）。故这 27 个名字 MUST 按 **D7** 以类级别名收敛，MUST NOT 纳入实例注册表。
   **已实测的类直调点（收敛后 MUST 全部仍可解析）**：
   - `VerificationPipeline._normalize_fail_signature`：生产代码 `core/pm_engine/engine.py` 的 `PMEngine._normalize_fail_signature`（`@staticmethod`）内直调；
   - `AgentRunner._entry_is_tool_result`：生产代码 `core/agent_runner/runner.py` 的延迟样本采集路径直调；
   - `VerificationPipeline._replan_errors_unconsumed` / `_extract_replan_error_items`：`tests/test_frozen_scenario_reservoir.py`；
   - `AgentRunner._normalize_run_id`（该名保留为真方法、不属 27 个别名组，但类直调点同样 MUST 保持可用）：`tests/test_run_cancel.py`；
   - `AgentRunner.parse_api_error_status`：`tests/test_provider_circuit.py`；`AgentRunner.classify_switch_error`：`tests/test_provider_failover.py`；
   - `PMEngine._is_fix_spec`：`tests/test_repair_lane_dedup.py`。
   （`.history/` 与 `.fenix/verify-serving/` 下的同名副本属临时产物，不在交付范围。）

### D2：注册表形态

- `PMEngine` / `AgentRunner`：注册表为 `{方法名: (子对象属性名, 目标方法名)}`，`__getattr__` 返回 `getattr(getattr(self, 子对象属性名), 目标方法名)`。`_verification`/`_dispatcher` 等为惰性 property，`__getattr__` 首次访问即触发构造（与 `pipeline.py` 既有惰性 property 先例一致）。
- `VerificationPipeline`：注册表分两组——**实例组** `{方法名: 子模块函数}`（函数以 `pipe` 为首参，85 个）→ `__getattr__` 返回 `functools.partial(func, self)`；**静态组**（首参非 `pipe`，5 个：`_extract_replan_error_items` / `_replan_errors_unconsumed` / `_normalize_fail_signature` / `_load_frozen_scenarios` / `_port_responds`）MUST NOT 经 `partial` 绑定 `self`（否则 `pipeline.py` 内既有的实例路径调用 `self._extract_replan_error_items(env_error)` 会变成 `func(self, env_error)` → `TypeError`），按 D7 以类级别名保留。**该 5 名 MUST NOT 写入 `__getattr__` 注册表**，避免 `partial` 覆盖 `Cls` 上的别名（别名是类属性，正常查找即命中，不会走到 `__getattr__`）。
- `VerificationPipeline` 的 `__getattr__` **已存在**（为 `__new__` 部分构造场景懒推导并缓存 `_context`；`tests/test_judge_efficiency.py`、`tests/test_verdict_evidence_taxonomy.py` 等依赖）。本变更 MUST 在其上**增量扩展**，MUST NOT 重写/覆盖：`_context` 分支 MUST 优先于注册表查询；`_pm` 缺失时 MUST `raise AttributeError`（MUST NOT 无限递归或吞异常）。
- 注册表 MUST 以源码内联 dict 声明（MUST NOT 动态反射扫描子模块），以便静态可读与代码审查。

### D3：`patch.object` 与子对象缝隙兼容性论证（回归硬门）

- `patch.object(facade, X)`：`mock.patch` 默认要求属性存在——`getattr(facade, X)` 经 `__getattr__` 成功返回，patch 成立；mock 在实例 `__dict__` 写值遮蔽 `__getattr__`；退出时删除实例属性 → 恢复转发。**兼容**。
- `patch.object(facade._verification, X)` / `engine._verification.X = MagicMock()`：作用于子对象，与本变更正交。**兼容**。
- `monkeypatch.setattr(runner, "_now", ...)`：`_now` 是真方法（MUST NOT 被误纳入注册表并删除）。契约测试 MUST 断言 `_now` 仍是显式类属性。

### D4：契约测试锁定

新增 `tests/test_facade_delegation_contract.py`：

- 三个类的 `__getattr__` 对注册表内每个名字都能解析到与子模块实现**同一函数**（`is` / `func.__wrapped__` 比对）。
- 未知名 `raise AttributeError`；dunder 名不转发。
- `hasattr(facade, "definitely_not_a_method") is False`。
- `patch.object(facade, X)` 与 `patch.object(facade.<子对象>, X)` 两种缝隙均生效。
- **类直调组（D7）**：对 27 个静态式名字逐一断言 (a) 仍是**类属性**（`name in vars(Cls)` 或 `Cls.<名>` 可解引用）、(b) `Cls.<名> is <目标函数>`（同一对象）、(c) D1 约束 4 列出的实测类直调点收敛后返回结果与收敛前一致。
- **静态组不得被 `partial` 覆盖**：断言 `self.<静态式名>` 与 `Cls.<静态式名>` 解析到同一目标，且实例路径调用不注入 `self`。
- 契约测试 MUST 在拆分后仍能枚举「原转发方法名全集」并逐一断言可解析（覆盖性硬门）。

### D5：与在飞 spec 的关系

- 与 `refactor-giant-classes` / `refactor-long-functions` **同文件**（`engine.py`/`pipeline.py`/`runner.py`）。
- 行区间虽零重叠，但 B 方案删 pipeline 236–560 整块会位移后续行号——本变更已选 A（只删方法体、不动长函数所在区间），位移影响最小；仍 MUST 串行落地（`depends_on` 已登记），后落地方重读符号。

### D6：不使用绝对行号锚定

任务与交付物以方法名 / 类名锚定（证据性 `文件:行` 引用 MAY 附，但 MUST 同时给出符号名；行号会随并行 SPEC 落地漂移）。

### D7：静态式转发以「类级别名」收敛（27 个）

D1 约束 4 列出的 27 个 `@staticmethod` 式转发（首参非 `self`/`pipe`）MUST 采用**类级别名**收敛，取代原方法体：

```python
class VerificationPipeline:
    # 取代：@staticmethod def _normalize_fail_signature(text): return _normalize_fail_signature(text)
    _normalize_fail_signature = staticmethod(_normalize_fail_signature)   # 名字与目标同名时 RHS 解析到模块级函数
    _extract_replan_error_items = staticmethod(_bg_extract_replan_error_items)
```

裁决依据：

- **保留两条解析路径**：`Cls.<名>(...)` 与 `self.<名>(...)` 都仍可解析（`staticmethod` 描述符经类访问返回原函数），既有类直调点零改动——这是 D1 约束 4 实测点的硬约束。
- **不重复签名**：别名是**纯对象绑定**，不书写参数列表与 docstring，满足 spec「双份签名不再存在」；`@staticmethod def ...` 转发壳（有签名）MUST 被别名取代，否则仍计为「剩余转发方法」（spec Scenario 1）。
- **目标形态已核实为可静态引用**：`FamilyGovernor._fix_prefix_depth/_is_fix_spec/_same_root`、`DispatchGuard._dispatch_backoffed`、`ProviderCircuit.parse_api_error_status/classify_switch_error/classify_transient_error`、`LivenessSupervisor._summarize_snapshot/_parse_verdict_json`、`SessionTracker._resumable_session_id/_extract_session_id/_extract_usage_info`、`branch_guard._extract_replan_error_items/_replan_errors_unconsumed`、`report_gate._normalize_fail_signature`、`scenario_gate._load_frozen_scenarios`、`serving._port_responds` 均为 `@staticmethod` 或模块级函数（**非** `classmethod`/实例方法），静态引用合法。
- **冲突名处理**：别名名与目标名同名时（如 `_normalize_fail_signature`），类体 `X = staticmethod(X)` 的 RHS 在赋值生效前解析到模块全局，合法；若目标为兄弟类静态方法、或本模块内存在同名遮蔽（如 `_replan_errors_unconsumed` 已以 `_bg_` 别名导入），MUST 显式写全限定目标（`staticmethod(Cls._x)` / `staticmethod(_bg_x)`），MUST NOT 依赖隐式解析。
- **链式依赖**：`PMEngine._normalize_fail_signature` 的目标是 `VerificationPipeline._normalize_fail_signature`——别名目标 MUST 是收敛后仍存在的类属性（即 pipeline 侧同样走 D7 别名），MUST NOT 指向被删除的转发。落地顺序（Migration Plan 阶段 1 先于阶段 3）天然满足，但 MUST 在验收中显式核对这条链。
- **回退面**：`Cls.<名>` 不再是 `FunctionDef`，`inspect.getsource(Cls.<名>)` 会指向目标函数源码——已核实 `tests/test_agent_runner_modules_contract.py` 的 `getsource` 只作用于 `_run_claude` / `_execute_agent_inner`（长函数、非转发，不受本变更影响）。

## Risks / Trade-offs

- **[风险] `__getattr__` 隐式行为、错误信息劣化** → 缓解：D2 要求注册表内联可读；D4 契约测试逐名断言；未知名严格 `raise AttributeError`。
- **[风险] `dir()` / IDE 补全退化** → 缓解：可在类上补 `__dir__` 返回 `super().__dir__() + list(注册表)`；已在 tasks 登记为可选增强。
- **[风险] 注册表遗漏一个名字致运行时 AttributeError** → 缓解：D4 覆盖性硬门（枚举原转发全集逐一断言）；全量回归兜底。
- **[风险] 惰性 property 在 `__getattr__` 内递归** → 缓解：`_verification` 等是类级 property（正常查找命中，不触发 `__getattr__`），无递归。
- **[风险] 类直调静态转发漏覆盖**（已实测存在 7 个名字、含 2 处生产调用点）→ 缓解：D1 约束 4 显式清单 + D7 类级别名 + D4 类直调组断言。
- **[风险] 静态式名字被误纳入实例注册表** → 一旦纳入，`self.<名>(...)` 经 `partial(func, self)` 多注一个 `self` → `TypeError`（`pipeline.py` 内 `self._extract_replan_error_items(env_error)` 即此形态）。缓解：D2 MUST NOT 写入 + D4「静态组不得被 `partial` 覆盖」断言。
- **[风险] `VerificationPipeline.__getattr__` 被重写覆盖** → 破坏 `__new__` 部分构造的 `_context` 懒推导（`tests/test_judge_efficiency.py` 等）。缓解：D2 增量合并约束。
- **[风险] 每态刷新带来的 `functools.partial` 元数据缺失**（`__name__`/`__doc__`）→ 影响面限于 introspection 与日志；`inspect.signature(partial)` 仍能还原去首参签名。缓解：D4 以「解析到同一目标函数」为断言口径（MUST NOT 以 `__name__` 为断言口径）；如需恢复元数据 MAY 在首次解析后缓存至实例 `__dict__`（须复核不破坏 `patch.object` 的进入/退出一致性）。
- **[风险] 静态守卫的 seam 集合随删除而变** → `tests/test_callsite_arity_guard.py` 与 `tests/test_fake_double_fidelity.py` 的判定基准取自 `core/` 类方法「唯一签名」集合。**已模拟实测**：删除全部门面转发（265 个形态；本变更实际删 263、多保留 2 个 stdlib 真方法，故该模拟对 seam 集合的影响是**上界**）后 seam 963 → 853，**无新增 seam、无签名变化**，两守卫判定集合不变（现存 4 处 arity 命中均为既有 `ARITY_WHITELIST` 内误报），候选集下限 100 亦满足 → 无实际破坏。阶段 4 仍 MUST 以全量回归复核。

## Migration Plan

1. 阶段 0：AST 清点三处转发全集（落盘 `facade-inventory.md`，**须按「实例式 / 静态式」二分标注**）+ 类直调审计 + 契约测试骨架 + 基线失败集合。
2. 阶段 1：`VerificationPipeline`（90 = 85 实例式 + 5 静态式；注册表最简单：纯模块函数）。
3. 阶段 2：`AgentRunner`（65 = 52 实例式 + 13 静态式；惰性 property）。
4. 阶段 3：`PMEngine`（110 = 100 实例式 + 10 静态式，最复杂；含指向 pipeline 静态名的链式别名）。
5. 阶段 4：全量回归、缝隙专项、类直调专项、契约覆盖性核对。

回滚：各阶段独立 commit。

## Open Questions

- 是否为三个类补 `__dir__` 以缓解 IDE 补全退化？（倾向补，成本低）
- ~~`PMEngine` 的 10 个类级静态转发是否存在真正的类直调？~~ **已审计（本轮评审实测）**：存在——`PMEngine._is_fix_spec`（`tests/test_repair_lane_dedup.py`）；且同类问题在另两个门面更多（`AgentRunner` 3 个名字、`VerificationPipeline` 3 个名字，含 2 处生产调用点）。处理方式已定为 D7 类级别名，不再保留为 `classmethod`。
