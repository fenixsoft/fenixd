# Tasks: refactor-facade-delegation

## Deliverables

```yaml
- path: core/pm_engine/verification/pipeline.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: tests/test_facade_delegation_contract.py
  kind: new
- path: spec/changes/refactor-facade-delegation/facade-inventory.md
  kind: new
- path: spec/changes/refactor-facade-delegation/facade-findings.md
  kind: new
```

> 三个宿主文件的 `kind: modify` 仅限**门面层**：新增 `__getattr__`（+ 可选 `__dir__`）与注册表、删除纯转发方法体。MUST NOT 修改子模块实现、MUST NOT 修改长函数所在区间（`refactor-long-functions` 的作业面）。
> 采用 design D1 方案 A（`__getattr__` 统一委托）——**调用点零改动**，故无被调用方文件、无测试改写文件进入交付集。

## 1. 阶段 0：清点与契约骨架

- [ ] 1.1 AST 清点三处转发全集：`PMEngine`（110）、`VerificationPipeline`（90）、`AgentRunner`（65），逐名落盘 `facade-inventory.md`（方法名 / 转发目标 / **形态二分：实例式（首参 `self`/`pipe`）或静态式（首参非 `self`）**；标注惰性 property 目标）
- [ ] 1.2 **三类**类直调审计（design D1 约束 4，不限于 `PMEngine`）：以 `Cls.<转发名>(...)` 全仓正则扫描，登记全部命中并逐名标注收敛方式。**已实测命中（MUST 逐一复核仍可用）**：`VerificationPipeline._normalize_fail_signature`（生产：`core/pm_engine/engine.py` 的 `PMEngine._normalize_fail_signature` 内）、`AgentRunner._entry_is_tool_result`（生产：`core/agent_runner/runner.py` 延迟样本采集路径）、`VerificationPipeline._replan_errors_unconsumed` / `_extract_replan_error_items`（`tests/test_frozen_scenario_reservoir.py`）、`AgentRunner._normalize_run_id`（`tests/test_run_cancel.py`）、`AgentRunner.parse_api_error_status`（`tests/test_provider_circuit.py`）、`AgentRunner.classify_switch_error`（`tests/test_provider_failover.py`）、`PMEngine._is_fix_spec`（`tests/test_repair_lane_dedup.py`）。扫描范围 MUST 排除 `.history/` 与 `.fenix/verify-serving/` 临时副本
- [ ] 1.3 审计真方法（非转发）被误纳入注册表的风险：确认 `AgentRunner._now`（`return time.monotonic()`）、`AgentRunner._normalize_run_id`（`return re.sub(...)`）这 2 个到 stdlib 的调用形态、以及 `AgentRunner._denoise_stderr` / `AgentRunner._parse_event_timestamp` 等**真实静态方法**（`@staticmethod` 但函数体非单条转发调用）保留为显式类属性，MUST NOT 纳入注册表或转成别名（spec「纯转发方法」判据已排除向 stdlib/第三方模块的调用）
- [ ] 1.4 建 `tests/test_facade_delegation_contract.py` 骨架：定义「原转发方法名全集」的断言框架（逐名可解析 + `is` 同一函数），并含**静态式组**断言（`Cls.<名> is <目标函数>`、实例路径不注入 `self`）与**类直调组**断言（1.2 命中点收敛后返回结果与收敛前一致）
- [ ] 1.5 记录全量基线失败集合；建疑点清单 `facade-findings.md`，只记录不修

## 2. 阶段 1：`VerificationPipeline`（90，最简）

- [ ] 2.1 建实例组注册表 `{方法名: 子模块函数}`（85 个，9 子模块全覆盖；函数以 `pipe`/`self` 为首参），**在既有 `__getattr__` 上增量扩展**（`_context` 懒推导分支 MUST 优先、`_pm` 缺失时 MUST `raise AttributeError`）；返回 `functools.partial(func, self)`；dunder 与未知名 `raise AttributeError`。**5 个静态式名字 MUST NOT 写入注册表**（design D2/D7）
- [ ] 2.2 删除 85 个实例式转发方法体（以方法名逐个勾对 `facade-inventory.md`，不以行区间锚定）
- [ ] 2.3 5 个静态式转发（`_extract_replan_error_items` / `_replan_errors_unconsumed` / `_normalize_fail_signature` / `_load_frozen_scenarios` / `_port_responds`）MUST 以类级别名（`name = staticmethod(目标)`，目标为模块函数时显式写全限定别名如 `_bg_extract_replan_error_items`）取代 `@staticmethod def` 转发壳（design D7）
- [ ] 2.4 运行契约测试 + 全量回归，确认门面方法经 `__getattr__` 逐一可解析且行为等价；专项确认 `pipeline.py` 内 `self._extract_replan_error_items(env_error)` 的实例路径调用与 `core/pm_engine/engine.py` 的 `VerificationPipeline._normalize_fail_signature(text)` 类直调均可用

## 3. 阶段 2：`AgentRunner`（71）

- [ ] 3.1 建实例组注册表 `{方法名: (子对象属性名, 目标方法名)}`（51 个：`_liveness` 12 / `_provider_circuit` 11 / `_prompt_builder` 7 / `_v2_server` 5 / `_token_accountant` 4 / `self` 首参模块函数 12），实现 `__getattr__`；**12 个静态式名字 MUST NOT 写入注册表**
- [ ] 3.2 删除 51 个实例式转发方法体（保留 `_now`（`time.monotonic`）与 `_normalize_run_id`（`re.sub`）这 2 个 stdlib 调用形态、以及 `_denoise_stderr` / `_parse_event_timestamp` 等真方法，以 `facade-inventory.md` 逐名勾对）
- [ ] 3.3 12 个静态式转发 MUST 以类级别名取代 `@staticmethod def` 转发壳（`_entry_is_tool_result`、`_format_gap_list`、`_invalid_completed_ids`、`_read_init_tools`、`parse_api_error_status`、`classify_switch_error`、`classify_transient_error`、`_summarize_snapshot`、`_parse_verdict_json`、`_resumable_session_id`、`_extract_session_id`、`_extract_usage_info`），目标写全限定名（如 `staticmethod(ProviderCircuit.parse_api_error_status)`、`staticmethod(SessionTracker._extract_session_id)`）
- [ ] 3.4 验证惰性 property（`_liveness`/`_provider_circuit`/`_prompt_builder`/`_v2_server`/`_token_accountant`）经 `__getattr__` 首访触发构造，且 `AgentRunner.__new__` 部分构造的测试模式仍可用（`tests/helpers.py`、`test_agent_runner.py`、`test_transient_backoff.py` 等 40+ 处）
- [ ] 3.5 核对门面名与实现名不同的两条（`record_transient_break`→`record_transient_error`、`is_global_transient_break_active`→`is_global_transient_break`）在注册表中正确映射
- [ ] 3.6 运行契约测试 + 全量回归；专项确认 `core/agent_runner/runner.py` 内 `AgentRunner._entry_is_tool_result(entry)`（生产类直调）与 `tests/test_transient_backoff.py` 内 `AgentRunner._denoise_stderr(...)`（真静态方法，非转发）均不受影响

## 4. 阶段 3：`PMEngine`（110，最复杂）

- [ ] 4.1 建实例组注册表（100 个）：`_verification` 43 / `_dispatcher` 21 / `_family` 15 / `_budget` 10 / `_recovery` 7 / `_reporting` 3 / `_spec_integrity` 1（注意门面名 `_check_spec_content_missing`≠实现名 `check_spec_content_missing`）；**10 个静态式名字 MUST NOT 写入注册表**
- [ ] 4.2 10 个静态式转发 MUST 以类级别名取代 `@staticmethod def` 转发壳（design D7）：`_fix_prefix_depth` / `_fix_strip_all` / `_is_fix_spec` / `_same_root` → `staticmethod(FamilyGovernor._<名>)`；`_dispatch_backoffed` → `staticmethod(DispatchGuard._dispatch_backoffed)`；`_run_file_died` / `_spec_fingerprint` / `_is_push_backoffed` / `_get_push_retry_count` → 各自目标
- [ ] 4.3 `PMEngine._normalize_fail_signature`（`staticmethod`）目标为 `VerificationPipeline._normalize_fail_signature`——MUST 显式写成 `staticmethod(VerificationPipeline._normalize_fail_signature)`，且 MUST 在阶段 1（pipeline 侧别名）落地后复核该链仍解析到同一函数（MUST NOT 指向被删转发）
- [ ] 4.4 删除 100 个实例式转发方法体（以 `facade-inventory.md` 逐名勾对）
- [ ] 4.5 运行契约测试 + 全量回归；核对 `scripts/verify-bug-repair-drive-engine.py`、`fenixd.py`、`core/admin_monitor.py` 的外部调用点**零改动**即可用；专项确认 `tests/test_repair_lane_dedup.py` 的 `PMEngine._is_fix_spec(...)` 类直调可用

## 5. 阶段 4：契约强化与收尾

- [ ] 5.1 可选增强：三类补 `__dir__`（`super().__dir__() + list(注册表)`）缓解 IDE 补全退化（design Open Question）
- [ ] 5.2 缝隙专项（design D3）：逐项验证 `patch.object(facade, X)`（6 处）与 `patch.object(facade.<子对象>, X)`、子对象赋值（203 处）、`monkeypatch.setattr(runner, "_now")` 全部仍生效
- [ ] 5.3 契约覆盖性硬门：断言「原转发方法名全集」（收敛对象 263 名 + 2 个 stdlib 保留名）逐名可解析，且未知名 `raise AttributeError`、`hasattr` 语义正确、dunder 不转发；**静态式组**断言 `Cls.<名> is <目标函数>` 且实例路径不注入 `self`；**类直调组**断言 1.2 全部命中点仍可调用且返回等价
- [ ] 5.4 运行 `bin/run_full_suite.py` 与基线比对，确认不新增失败；**并单独确认两个 AST 静态守卫**（`tests/test_callsite_arity_guard.py`、`tests/test_fake_double_fidelity.py`）仍绿——二者判定基准取自 `core/` 类方法「唯一签名」seam 集合，删除 263 个门面方法会使该集合缩小（设计期模拟：963 → 853，无新增 seam、无签名变化，预期不变；若出现新增失败，须核明是守卫集合变化而非产品行为变化）
- [ ] 5.5 汇报疑点清单最终态（`facade-findings.md`）
- [ ] 5.6 逐项勾选本 tasks.md 全部已完成任务
