# Design: refactor-facade-delegation

## Context

前三条重构把三个巨型实现拆到子模块，宿主类保留了海量一行转发方法，形成三层调用链。AST 全量扫描（判据：函数体仅一条 `return`，返回 `self.<子对象>.<方法>(...)`、子模块函数调用或兄弟类方法调用）：

| 宿主类 | 转发 / 总方法 | 形态 |
|---|---|---|
| `PMEngine`（`engine.py`） | **110 / 206** | `_verification` 43、`_dispatcher` 21、`_family` 15、`_budget` 10、`_recovery` 7、`_reporting` 3、`_spec_integrity` 1、**类级静态转发到兄弟类** 10 |
| `VerificationPipeline`（`verification/pipeline.py`） | **90 / 93** | 连续整块（236–560 行）转发到本包 9 子模块的模块级函数（首参 `pipe`） |
| `AgentRunner`（`runner.py`） | **71 / 148** | `maintenance_runs` 13、`_liveness` 12、`_provider_circuit` 11、`result_gate` 10、`_prompt_builder` 7、`_v2_server` 5、`_token_accountant` 4、类方法 8、`latency` 1 |

**关键实测（决定方案选择）：**

- **字符串路径 patch：零命中**。全仓**不存在** `patch("core.pm_engine.engine.X")` / `patch("...pipeline.X")` / `patch("...runner.X")` 指向任何转发方法。唯一模块字符串 patch 是 `core.agent_runner.runner.time.time/sleep`（stdlib 属性，与转发无关）。
- **对象级缝隙**：`patch.object(facade, X)` 6 处（多为 `_send_human_escalation_alert`、`_sibling_*`、`_run_agent_worker`）；测试直接对**子对象**赋值 Mock（`engine._verification.X = ...`）**203 处**——后者与门面方案正交。
- **爆炸半径**：转发方法调用点共 ~1910 处，其中**真外部生产调用点仅 35 处**，82–88% 是测试；同包兄弟模块反向穿越门面 467 处（`dispatch.py` 85 处 `pm._enqueue` 等）。
- **行区间重叠**：`pipeline.py` 转发块（236–560）与长函数（563–1811）**零重叠**；`runner.py` 转发三簇（956–995、3070、3412–3797）与 `_execute_agent_inner`（1593–2499）**零重叠**。

## Goals / Non-Goals

**Goals:**

- 消除门面与子模块实现的**双份签名 / docstring 维护**。
- 让宿主类**真正变小**（删掉 ~271 个转发方法体），而非「从实现巨型变成转发巨型」。
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
| 宿主类真正变小 | **是**（删 ~271 方法体，约 1,350 行） | 是 | **否**（转发壳保留） |
| 风险 | 隐式行为、`dir()`/`hasattr()` 语义 | 工作面最大、易引入行为变化、且与 `refactor-giant-classes`（拆 dispatch.py，内含大量穿越调用）规格耦合 | 不解决阅读成本 |

**裁决：A。** 理由：在「零调用点破坏」这一本项目最硬的风险约束下，A 与 C 并列最优；而 C 不解决「宿主类没变小」这一本 spec 的核心目标；B 虽最彻底，但 1,760 处改写（尤其 1,134 处测试）引入的行为变化风险与本项目「零行为变化」红线冲突，且与 `refactor-giant-classes` 形成规格耦合。A 以「显式注册表」换取零调用点改动，且注册表本身是比 90 个一行方法**更集中**的单一事实源。

**`__getattr__` 实现约束：**

1. 对 `__` 开头 / `__` 结尾的 dunder 名 MUST NOT 转发（避免破坏 pickle/copy/`isinstance` 协议）——直接 `raise AttributeError`。
2. 名字不在注册表时 MUST `raise AttributeError`（使 `hasattr`/`getattr(...,default)` 语义正确，MUST NOT 恒真）。
3. 三个类的注册表 MUST 覆盖全部原转发方法名，逐名可核对；注册表由契约测试锁定（D4）。
4. `PMEngine` 的 10 个**类级静态转发**（`FamilyGovernor._is_fix_spec` 等）不适用实例 `__getattr__` 的类属性访问路径——默认经实例访问（`self._is_fix_spec`）由 `__getattr__` 覆盖；MUST 审计是否存在 `PMEngine._is_fix_spec(...)` 式**类直调**，若有则该名 MUST 保留为显式 classmethod。

### D2：注册表形态

- `PMEngine` / `AgentRunner`：注册表为 `{方法名: (子对象属性名, 目标方法名)}`，`__getattr__` 返回 `getattr(getattr(self, 子对象属性名), 目标方法名)`。`_verification`/`_dispatcher` 等为惰性 property，`__getattr__` 首次访问即触发构造（与 `pipeline.py` 既有惰性 property 先例一致）。
- `VerificationPipeline`：注册表为 `{方法名: 子模块函数}`（函数以 `pipe` 为首参），`__getattr__` 返回 `functools.partial(func, self)`。
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
- 契约测试 MUST 在拆分后仍能枚举「原转发方法名全集」并逐一断言可解析（覆盖性硬门）。

### D5：与在飞 spec 的关系

- 与 `refactor-giant-classes` / `refactor-long-functions` **同文件**（`engine.py`/`pipeline.py`/`runner.py`）。
- 行区间虽零重叠，但 B 方案删 pipeline 236–560 整块会位移后续行号——本变更已选 A（只删方法体、不动长函数所在区间），位移影响最小；仍 MUST 串行落地（`depends_on` 已登记），后落地方重读符号。

### D6：不使用绝对行号锚定

任务与交付物以方法名 / 类名锚定。

## Risks / Trade-offs

- **[风险] `__getattr__` 隐式行为、错误信息劣化** → 缓解：D2 要求注册表内联可读；D4 契约测试逐名断言；未知名严格 `raise AttributeError`。
- **[风险] `dir()` / IDE 补全退化** → 缓解：可在类上补 `__dir__` 返回 `super().__dir__() + list(注册表)`；已在 tasks 登记为可选增强。
- **[风险] 注册表遗漏一个名字致运行时 AttributeError** → 缓解：D4 覆盖性硬门（枚举原转发全集逐一断言）；全量回归兜底。
- **[风险] 惰性 property 在 `__getattr__` 内递归** → 缓解：`_verification` 等是类级 property（正常查找命中，不触发 `__getattr__`），无递归。
- **[风险] 类直调静态转发漏覆盖** → 缓解：D1 约束 4 显式审计。

## Migration Plan

1. 阶段 0：AST 清点三处转发全集（落盘 `facade-inventory.md`）+ 契约测试骨架 + 基线失败集合。
2. 阶段 1：`VerificationPipeline`（90，注册表最简单：纯模块函数）。
3. 阶段 2：`AgentRunner`（71，惰性 property）。
4. 阶段 3：`PMEngine`（110，含 10 个类级静态转发，最复杂）。
5. 阶段 4：全量回归、缝隙专项、契约覆盖性核对。

回滚：各阶段独立 commit。

## Open Questions

- 是否为三个类补 `__dir__` 以缓解 IDE 补全退化？（倾向补，成本低）
- `PMEngine` 的 10 个类级静态转发是否存在真正的类直调（需审计后决定保留为 classmethod 还是并入注册表）？
