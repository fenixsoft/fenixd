# Design: add-lost-semantics-regression-tests

## Context

`c310ee5` 拆分 test_core.py 时 4 组实质测试被空壳化，断言丢失；空壳已删除，语义裸奔。本 spec 只补测试、不改生产行为。

## Goals / Non-Goals

**Goals:**
- 4 项语义各有一组对齐当前源码的真实回归测试
- 测试可长期维护：夹具复用各域既有范式（`make_scheduler`/`__new__` 桩链/`FakeReviewRunner` 等），不另起炉灶

**Non-Goals:**
- 不复活旧属性名（`_replan_count`/`_max_replans` 已不存在；`_circuit_breaker_is_open` 已迁 ProviderCircuit）
- 不修改 core/ 生产行为；实现侧语义缺失只登记不补写

## Decisions

### D1 — 每项先调查再落测（防「测旧设计」）
实现者动手前必须先 Read 对应源码确认当前机制形态：
1. replan：查 `core/pm_engine/` 中 planner 产物不合格/重派循环的现状（属性名、上限常量、退回去向）。若上限机制已不存在，测试改为锁定「当前实际行为」并在 findings 登记 `spec-inconsistency` 供人工裁决是否需要实现侧改进。
2. 断路器：`core/agent_runner/provider_circuit.py` ProviderCircuit 的 open 判定 + `core/pm_engine/verification.py` 对 verifier 失败的分类路径。测试从 ProviderCircuit 状态构造出发驱动 verification 层。
3. 统一失败信号：`verification.py` 各失败形态的汇聚点（bug-found 判定、`_verify_fail_rounds` 计数、family 信号）。用例按失败形态参数化。
4. 截图时机：`core/verify_engine/` 截图触发点与断言执行状态的关系。优先真实浏览器路径（沿用原测试的 playwright/浏览器夹具思路）；CI 无浏览器环境用夹具/mock 浏览器锁定「未执行⇒无截图调用」即可，不强求真实渲染。

### D2 — 测试落点
- 1/2/3 → `tests/test_pm_recovery.py`、`tests/test_pm_verification.py` 各自域内新类
- 4 → 新文件 `tests/test_verify_screenshot_timing.py`
- 全部走 pytest，不引入新依赖

### D3 — 验收口径
- `python3 -m pytest tests/test_pm_recovery.py tests/test_pm_verification.py tests/test_verify_screenshot_timing.py -q` 全绿
- 全量 `python3 -m pytest tests/ -q` 不引入新失败
- 每组测试含至少一条「防回归方向」断言（如：错误行为发生时计数必须递增/状态必须保持）

## Risks / Trade-offs

- 风险：调查后发现某语义在当前实现中「从来没被正确实现」→ 测试会写不出通过版。处置：按 D1 登记为发现，不硬造永真测试（那正是本次清理要消灭的东西）。
- 截图时机测试对浏览器环境敏感 → D1-4 允许 mock 浏览器，锁定调用时机而非渲染结果。

## Migration Plan

纯增量测试，无迁移。与 2026-09-07 测试清理（空壳删除）为互补关系：清理删掉假的，本 spec 补回真的。

## Open Questions

- replan 上限若确认实现侧缺失，是否立项改进——留给用户判定（测试侧只登记）。
