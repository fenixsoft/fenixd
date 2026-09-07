# Tasks: add-lost-semantics-regression-tests

## 1. 调查与落测：replan 上限

- [ ] 1.1 调查 `core/pm_engine/` 当前 replan/重派循环机制形态（属性名/上限常量/退回去向），结论写入交付说明；若机制缺失则按 design D1 登记发现并以「锁定当前实际行为」方式落测
- [ ] 1.2 在 `tests/test_pm_recovery.py` 新增真实链路测试：上限退回 + 成功后计数归零（对应 spec 两个 Scenario）

## 2. 落测：verifier 断路器保持

- [ ] 2.1 在 `tests/test_pm_verification.py` 新增 ProviderCircuit open 驱动的 verification 层测试：状态保持、不递增失败轮次、基础设施口径记录（spec Scenario「熔断打开时 verifier 失败不误判 bug-found」）

## 3. 落测：验证失败形态归一

- [ ] 3.1 在 `tests/test_pm_verification.py` 新增参数化测试覆盖三种失败形态（run 异常 / verdict bug-found / 结果文件畸形）统一失败信号与轮次计数，及通过归零（spec 两个 Scenario）

## 4. 落测：截图时机门禁

- [ ] 4.1 调查 `core/verify_engine/` 截图触发点与断言执行的绑定关系，确定可测注入点（真实浏览器或 mock 浏览器，按 design D1-4）
- [ ] 4.2 新建 `tests/test_verify_screenshot_timing.py`：断言未执行不出图 + 断言执行后截图可归因（spec 两个 Scenario）

## 5. 收口

- [ ] 5.1 域内测试全绿：`python3 -m pytest tests/test_pm_recovery.py tests/test_pm_verification.py tests/test_verify_screenshot_timing.py -q`
- [ ] 5.2 全量回归：`python3 -m pytest tests/ -q` 不引入新失败
- [ ] 5.3 交付说明登记：replan 调查结论（含是否需要实现侧改进的建议）、截图注入点选型、任何 xfail 项及理由

## Deliverables

```yaml
- path: tests/test_pm_recovery.py
  kind: modify
- path: tests/test_pm_verification.py
  kind: modify
- path: tests/test_verify_screenshot_timing.py
  kind: new
```
