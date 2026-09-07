# Proposal: add-lost-semantics-regression-tests

## Why

2026-09-07 全库测试审查发现：历史提交 `c310ee5`（refactor-test-structure，把巨型 test_core.py 拆分为域文件）在拆分过程中把多个实质测试类替换成了同名空壳（仅 `assertIsNotNone` / 只断言 mock / 自算自断言），**断言丢失而非迁移**。空壳已随测试清理（同日 A 级删除）移除，但其原本保护的 4 项框架语义经 grep 证实**现库无任何测试保护**：

1. **replan 上限退回**：PMEngine 对 planner 产物不合格的 replan 循环缺少上限退回保护（原 TestPMEngineReplanLoop；注意生产代码已无 `_replan_count`/`_max_replans` 属性——实现侧机制形态需以当前源码为准调查后落测）。
2. **verifier 断路器保持**：provider 熔断打开时 verifier 基础设施失败不得误判为 bug-found、状态应保持（原 TestVerifierCircuitOpenHoldsState；熔断已迁 `core/agent_runner/provider_circuit.py`，需按新集成点落测）。
3. **统一验证失败信号**：验证失败的多种形态（verifier run 失败 / verdict bug-found / 基础设施异常）应归一到统一失败信号并正确计数 `_verify_fail_rounds`（原 TestUniformVerifyFailure）。
4. **截图时机门禁**：verify_engine 截图仅在断言真实执行后产生，断言未执行的阶段不得出图（原 TestVerifyEngineScreenshotTiming，119 行真实浏览器测试被空壳化）。

这 4 项都是烧钱事故高发区（假失败重试、误判打回、截图噪音），无保护意味着回归可静默复发。

## What Changes

- 新增/补全 4 组真实回归测试，替代被删除的空壳，断言对齐**当前源码行为**（禁止复活已不存在的旧属性名/旧 mock 点）。
- 不修改任何生产代码；若调查发现某项语义在当前实现中确实缺失（而非仅测试缺失），在测试中以 xfail 呈现并在交付说明中登记，不擅自改行为。

## Capabilities

### regression-coverage
- replan 循环上限退回的真实链路测试
- provider 熔断打开时 verifier 状态保持测试
- 验证失败形态归一与轮次计数测试
- 截图时机门禁测试

## Impact

- 涉及文件：`tests/test_pm_recovery.py`（modify）、`tests/test_pm_verification.py`（modify）、截图时机新文件（new，落点由实现者按域归属决定，建议 `tests/test_verify_screenshot_timing.py`）
- 不改 core/、agents/、dashboard 前端
- 全量测试套件必须保持全绿
