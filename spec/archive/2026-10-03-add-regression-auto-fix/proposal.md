## Why

测试回归页签已有「立即执行全量回归」按钮与问题列表（失败/错误/超时/长耗时），但发现问题后没有任何修复入口——用户必须人工阅读问题列表、手工修复。code-fix 车道已具备成熟的修复机制（台账→批派 worktree→回归验证→失败自愈），且已有手动触发先例（add-code-fix-manual-trigger），把回归问题接入该车道只需补一条「回归问题→台账条目」的转换链路与一个触发按钮。

## What Changes

- 测试回归页签（RegressionTab）在「立即执行全量回归」按钮旁新增「自动修复回归问题」按钮：问题列表存在异常用例时可点，点击后写文件信号触发修复；无异常/无快照时禁用。
- 新增 API：`POST /api/regression/fix`（校验快照存在且有异常 → 原子写 `.fenix/regression_fix_request.json` 信号）与 `GET /api/regression/fix-result`（受理判定回链，读 `.fenix/regression_fix_request_result.json`）。
- daemon 主循环新增信号消费 `_check_regression_fix_requests`（与 `_check_code_fix_requests` 同构）：原子消费信号 → 读最近一次回归快照 → 把失败/错误/超时/长耗时用例转换为 code-fix 台账条目（`upsert_findings`，category 以 `regression-` 为前缀）→ 以 `override_enabled=True` 调 `checkpoint()` → 原子写结果文件回链。
- 台账条目语义补充：category 以 `regression-` 为前缀的条目，若在最近一次回归快照中仍出现但台账 status 已非 open，消费时重开为 open（保证同问题复发可再次触发修复，否则链会以 no_open_items 拒绝、按钮一次性失效）。
- 长耗时用例的修复语义固化为条目文案：以不改变测试通过结果为前提，允许优化被测实现或测试代码本身（去冗余 sleep、修慢 fixture、并发化等）；失败/错误用例照常修复。

## Capabilities

### New Capabilities
- `regression-auto-fix`: 回归问题的手动一键自动修复——前端按钮、触发/回链 API、daemon 信号消费、回归快照→code-fix 台账条目转换（含去重、重开、超时兜底定位与长耗时修复语义）。

### Modified Capabilities

（无——既有 test-regression-tab 能力的展示行为不变，本能力是页签上的新增按钮与新增后端车道入口；code-fix 车道批派/验证/合并机制零改动。）

## Impact

- `core/dashboard/static/src/pages/projects/components/RegressionTab.tsx`：新增按钮与回链反馈。
- `core/dashboard/static/src/services/dashboard.ts`：新增 `fixRegression` / `getRegressionFixResult` API 封装。
- `core/dashboard/routes/regression_routes.py`：新增 POST /api/regression/fix 与 GET /api/regression/fix-result。
- `fenixd.py`：新增 `_check_regression_fix_requests` 消费方法与主循环挂载点。
- `core/code_fix.py`：新增回归快照→台账 findings 转换纯函数与 regression 类目条目重开辅助函数（不改既有批派/验证/合并路径）。
- 复用不改：`core/code_review.py` 的 `upsert_findings`/`fingerprint` 去重语义、`CodeFixOrchestrator.checkpoint` 全部守卫（单飞/无 open 条目/失败保留/回归契约 fail-closed）、code-fix 进度展示（质量页签 CodeFixProgressCard）。
- 风险面：消费端在 checkpoint 拒绝（如 code-fix 链在飞）时条目已入台账——在飞链下一批自然吸收，属预期行为；需在回链文案中如实呈现。
