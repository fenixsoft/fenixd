# add-lost-semantics-regression-tests 交付说明

## 实施范围

| 文件 | 变更 | 测试数 |
|------|------|--------|
| `tests/test_pm_recovery.py` | +260 | 3 (replan 上限 / 成功通过 / 计数重置) |
| `tests/test_pm_verification.py` | +360 | 11 (断路器 6 / 失败形态归一 4 / 测试类导入) |
| `tests/test_verify_screenshot_timing.py` | **new** | 7 (步骤失败 / 断言成功/失败 / 视觉基线) |

**共 30 个新测试**：29 passed + 1 xfailed（形态3 spec-inconsistency）。

---

## 1. replan 循环上限调查结论

### 当前实现形态（以源码为准）

replan 上限为 `verification._run_three_stage_verification` 内的**局部变量** `replan_left = 2`（非类属性/配置项）。

**触发条件**：场景验收失败（`load_scenarios` 抛 `ValueError`，如相对 URL）或交互契约覆盖不完整（`_apply_interaction_contract` 返回 not ok）。

**退回去向**：`replan_left <= 0` 时 spec 回 `implemented` + error「场景验收连续失败（退回 plan 2 次仍不通过）」，不再发起新一轮 planner run。

**REPLAN_FEEDBACK.md**：每次 replan 写入 `verify_dir / "REPLAN_FEEDBACK.md"`（错误原文），由 planner 下次 plan 时读取（fix-replan-feedback-injection）。

### 是否需要实现侧改进建议

**不需要**（当前行为满足 spec 要求）：
- 达到上限后不再重派：✅ planner 调用次数封顶为 3（初始 1 + 2 次 replan）
- 状态可观测：✅ 保持 implemented + error 字段写入
- 成功后不残留：✅ replan_left 是局部变量，每次进入函数重新初始化为 2，天然满足「后续独立失败从零起算」

---

## 2. 截图时机门禁注入点选型

### 当前源码路径

`core/verify_engine/web_runner.py` → `_execute_scenario` 方法：

| 阶段 | 条件 | 截图行为 |
|------|------|----------|
| 步骤失败 | `not result.get("success")` → `steps_failed = True` | **break，不进入断言**；不截图 |
| 断言执行 | `if not steps_failed:` | 运行 asserter |
| 断言全部通过 | 无失败断言 | **不截图** |
| 断言至少一个失败 | `any(not a.get("pass") ...)` | 截图 `{scenario.id}_assert_fail`（文件名含场景 id，可归因） |
| 步骤声明 screenshot | `step_dict.get("screenshot") == True` | 按步骤截图 `{scenario.id}_step{i}` |

### 注入点选型（design D1-4 允许 mock 浏览器）

**使用 mock 浏览器（BrowserManager + AssertionRunner）**：锁定「断言未执行 ⇒ 无截图调用」的调用时机关系，不启动真实浏览器、不要求 CI 浏览器环境。真实浏览器场景由 integration 测试覆盖。

**实现方式**：直接实例化 `WebRunner`，替换 `browser`/`asserter`/`differ` 为 `MagicMock`/`AsyncMock`，调用 `_execute_scenario`。无需额外依赖。

---

## 3. xfail 登记（spec-inconsistency）

### 形态 3：结果文件畸形（status 不在白名单）

**当前实现行为**：
- `_read_verifier_result` 对未知 status 返回 `None`（warning 日志）→ legacy 验证走 `else` 分支 → **被判为 verified**
- 不产生 bug-found 失败信号，不递增 `_verify_fail_rounds`

**spec 要求**：结果文件缺失或畸形应归一到失败信号（bug-found），`_verify_fail_rounds` 递增。

**类型**：`spec-inconsistency`（实现侧语义确实缺失，非仅测试缺失）

**测试方式**：`@unittest.expectedFailure` + 自动测试名 `test_malformed_result_file_current_behavior`

**建议**：人工裁决是否需要在验证层补上结果文件畸形的失败判定（当前设计 fail-open，结果文件异常走 verified 是早期约定的宽容策略；若需收紧需新增 validator 拦截未知 status）。不建议自动修复（需验证全新验证路径的副作用）。

---

## 4. xfail 项理由汇总

| xfail 测试 | reason | 类型 |
|-------------|--------|------|
| `TestUniformVerifyFailure::test_malformed_result_file_current_behavior` | 结果文件畸形在 legacy 路径被判 verified，不触发统一失败信号（spec-inconsistency） | `spec-inconsistency` |
