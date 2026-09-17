# facade-findings：疑点清单（refactor-facade-delegation）

> 本清单只记录、不修复（spec「不顺手修 bug」约束）。阶段 0 建立，阶段 4 汇报最终态（tasks 5.5）。

## 疑点

### F-01 同包兄弟模块反向穿越门面（467 处）

`dispatch.py` 等兄弟模块以 `pm._enqueue` 形式反向调用 `PMEngine` 私有转发方法（design 实测 467 处，如 `dispatch.py` 85 处 `pm._enqueue`）。这违反 `refactor-verification-module` 已立的 D2b「组件 MUST NOT 回引门面私有方法」规则。

- **影响**：本变更采用 `__getattr__` 统一委托后这些调用**仍可用**（经注册表解析），不产生断链；但「组件回引门面」的架构异味留存。
- **归属**：`refactor-giant-classes` / `refactor-verification-module` D2b 范畴（非本 SPEC 作业面）。
- **处置**：记录，不修。

### F-02 `AgentRunner` 实例式转发计数与 design 表格不符

design 表格：AgentRunner 实例式 52；本变更阶段 0 实测：**56**。差额为 signal-kill 冷却族 4 个转发（`is_signal_kill_cooldown` / `signal_kill_cooldown_until` / `_signal_kill_counts` / `_record_signal_kill`）与 `is_global_transient_break_active`（design 归 `_provider_circuit` 11，实测 15）。design 明示「逐名权威清单以阶段 0 落盘的 facade-inventory.md 为准」，本变更以清单为准。

### F-03 `VerificationPipeline._port_responds` 等静态式转发的类直调点缺实测命中

design D1 约束 4 实测清单未含 `_port_responds` / `_load_frozen_scenarios` 的类直调命中（仅 `_normalize_fail_signature` / `_extract_replan_error_items` / `_replan_errors_unconsumed` 有命中）。D7 仍统一收敛为类级别名，两条解析路径都保留；无命中的名字收敛后经契约测试覆盖性硬门逐名断言类属性存在。

### F-04 `PMEngine._fix_prefix_depth` 无 `@staticmethod` 装饰器

AST 扫描显示 `_fix_prefix_depth`（line 2610）无 `@staticmethod` 装饰器但首参非 `self`。以 D7 类级别名收敛（`_fix_prefix_depth = staticmethod(FamilyGovernor._fix_prefix_depth)`）后，类直调与实例直调两条路径都可用——比原形态（无装饰器时类直调可用、实例直调会多绑 self）更稳。契约测试类直调组覆盖。

### F-05 惰性 property 首访构造的副作用面

`__getattr__` 委托使「属性访问」首次触发子对象构造（`_liveness` 等惰性 property）。副作用：`hasattr(facade, "某转发名")` 为真时若未知名误入注册表会触发构造——注册表内联枚举已排除该风险；部分构造测试（`__new__` 绕过 `__init__`）的实例访问转发名会构造子对象，子对象构造器仅存 `self._pm = pm` 引用，无 IO 副作用，安全（design D2 / tasks 3.4 专项验证）。

### F-06 `patch.object(facade, X)` 的 mock 写实例 `__dict__` 与惰性 property 缓存共存

`patch.object` 写 `__dict__` 遮蔽 `__getattr__`；而惰性 property 缓存也写 `__dict__`（如 `_verification_instance`）。两者键不同（方法名 vs `_<名>_instance`），无冲突；退出 patch 删方法名属性后 `__getattr__` 恢复。契约测试缝隙专项覆盖（tasks 5.2）。

### F-07 门面名 ≠ 实现名映射（3 处）

注册表显式映射清单（设计已点名，本变更实现时逐处核对）：

| 门面名 | 实现名 | 所在 |
|---|---|---|
| `_check_spec_content_missing` | `check_spec_content_missing` | PMEngine → `_spec_integrity` |
| `record_transient_break` | `record_transient_error` | AgentRunner → `_provider_circuit` |
| `is_global_transient_break_active` | `is_global_transient_break` | AgentRunner → `_provider_circuit` |

### F-08 `VerificationPipeline.__getattr__` 增量扩展的语义约束

既有 `__getattr__` 承担 `_context` 懒推导（`__new__` 部分构造场景）。本变更增量扩展 MUST 保持：`_context` 分支优先；注册表查询在其后；`_pm` 缺失时 `raise AttributeError`（不得无限递归）。`tests/test_judge_efficiency.py` / `tests/test_verdict_evidence_taxonomy.py` 依赖既有语义（design D2）。

### F-09 全量回归基线与待查失败

阶段 0 基线全量套件运行记录（以 `bin/run_full_suite.py --timeout 3600` 落盘 `.history/baseline_full.log`）。基线上已存在的失败属存量，MUST NOT 归因本变更；阶段 4 以 `--baseline` 归类。

## 记录说明

- 建立时间：2026-09-18（阶段 0）。
- 更新规则：阶段 4（tasks 5.5）更新最终态；已修复/已消除的疑点标注「关闭」。
