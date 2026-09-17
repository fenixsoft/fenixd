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

- [ ] 1.1 AST 清点三处转发全集：`PMEngine`（110）、`VerificationPipeline`（90）、`AgentRunner`（71），逐名落盘 `facade-inventory.md`（方法名 / 原行 / 转发目标；标注类级静态转发与惰性 property 目标）
- [ ] 1.2 审计 `PMEngine` 的 10 个类级静态转发是否存在**类直调**（`PMEngine._is_fix_spec(...)` 式），登记需保留为 classmethod 的名字（design D1 约束 4）
- [ ] 1.3 审计真方法（非转发）被误纳入注册表的风险：确认 `AgentRunner._now` 等 MUST 保留为显式类属性
- [ ] 1.4 建 `tests/test_facade_delegation_contract.py` 骨架：定义「原转发方法名全集」的断言框架（逐名可解析 + `is` 同一函数）
- [ ] 1.5 记录全量基线失败集合；建疑点清单 `facade-findings.md`，只记录不修

## 2. 阶段 1：`VerificationPipeline`（90，最简）

- [ ] 2.1 建注册表 `{方法名: 子模块函数}`（9 子模块全覆盖），实现 `__getattr__`（返回 `functools.partial(func, self)`；dunder 与未知名 `raise AttributeError`）
- [ ] 2.2 删除 236–560 行的 90 个转发方法体
- [ ] 2.3 运行契约测试 + 全量回归，确认门面方法经 `__getattr__` 逐一可解析且行为等价

## 3. 阶段 2：`AgentRunner`（71）

- [ ] 3.1 建注册表 `{方法名: (子对象属性名, 目标方法名)}`（`maintenance_runs` 13 / `_liveness` 12 / `_provider_circuit` 11 / `result_gate` 10 / `_prompt_builder` 7 / `_v2_server` 5 / `_token_accountant` 4 / 类方法 8 / `latency` 1），实现 `__getattr__`
- [ ] 3.2 删除 71 个转发方法体（保留 `_now` 等真方法）
- [ ] 3.3 验证惰性 property（`_liveness`/`_provider_circuit`/`_prompt_builder`/`_v2_server`/`_token_accountant`）经 `__getattr__` 首访触发构造，且 `AgentRunner.__new__` 部分构造的测试模式仍可用
- [ ] 3.4 项 3.1.1：核对门面名与实现名不同的两条（`record_transient_break`→`record_transient_error`、`is_global_transient_break_active`→`is_global_transient_break`）在注册表中正确映射
- [ ] 3.5 运行契约测试 + 全量回归

## 4. 阶段 3：`PMEngine`（110，最复杂）

- [ ] 4.1 建注册表：`_verification` 43 / `_dispatcher` 21 / `_family` 15 / `_budget` 10 / `_recovery` 7 / `_reporting` 3 / `_spec_integrity` 1（注意门面名 `_check_spec_content_missing`≠实现名 `check_spec_content_missing`）
- [ ] 4.2 处理 10 个类级静态转发：能经实例 `__getattr__` 覆盖者并入注册表；存在类直调者保留为显式 `classmethod`（依 1.2 审计结论）
- [ ] 4.3 删除 110 个转发方法体
- [ ] 4.4 运行契约测试 + 全量回归；核对 `scripts/verify-bug-repair-drive-engine.py`、`fenixd.py`、`core/admin_monitor.py` 的外部调用点**零改动**即可用

## 5. 阶段 4：契约强化与收尾

- [ ] 5.1 可选增强：三类补 `__dir__`（`super().__dir__() + list(注册表)`）缓解 IDE 补全退化（design Open Question）
- [ ] 5.2 缝隙专项（design D3）：逐项验证 `patch.object(facade, X)`（6 处）与 `patch.object(facade.<子对象>, X)`、子对象赋值（203 处）、`monkeypatch.setattr(runner, "_now")` 全部仍生效
- [ ] 5.3 契约覆盖性硬门：断言「原转发方法名全集」逐名可解析，且未知名 `raise AttributeError`、`hasattr` 语义正确、dunder 不转发
- [ ] 5.4 运行 `bin/run_full_suite.py` 与基线比对，确认不新增失败
- [ ] 5.5 汇报疑点清单最终态（`facade-findings.md`）
- [ ] 5.6 逐项勾选本 tasks.md 全部已完成任务
