## Why

自动修复代码问题（`admin.code_review_fix`，add-code-review-auto-fix）当前只有两路后台激活：审查收尾时与异常中断续做时。用户打开「自动修复代码问题」开关后，若想立刻修掉台账里的 open 条目，只能被动等框架下一次后台调度——而「手动触发审查」按钮（POST /api/code-review/run）只能触发审查本身，不能直接拉起修复。需要在质量页签提供手动「立即自动修复」按钮，点了就投递一批，不必等后台调度。

## What Changes

- 质量页签（QualityTab）动作按钮组新增「立即自动修复」按钮：点击后向目标项目写手动修复触发信号（文件信号族新成员），由 daemon 主循环消费。
- dashboard 路由新增 `POST /api/code-review/fix-run`（写 `.fenix/code_fix_request.json` 信号，O_CREAT|O_EXCL 原子独占创建）与 `GET /api/code-review/fix-run-result`（只读本次触发判定结果）。
- daemon 主循环新增 `.fenix/code_fix_request.json` 消费函数：调 `CodeFixOrchestrator.checkpoint()` 投递一批，并把判定结果（`{triggered, reason}`）写回 `.fenix/code_fix_request_result.json` 供前端回显。
- **手动即临时授权**（用户决策）：手动触发绕过「自动修复代码问题」总开关（`enabled`）守卫——即使开关关闭，手动点按钮也修复这一批；其余安全守卫全部保留（单飞 already_running、无 open 条目、失败保留集合、回归契约 fail-closed）。
- checkpoint 判定被拒时（无待修条目 / 已有修复在跑 / 回归契约缺失等），前端以明确文案回显具体原因，不让用户对着无反应的按钮猜。

## Capabilities

### New Capabilities

- `code-fix-manual-trigger`: 自动修复代码问题的手动触发入口——dashboard 信号端点、daemon 消费与结果反馈、checkpoint 临时授权语义、前端按钮与原因回显。

### Modified Capabilities

<!-- 无：add-code-review-auto-fix 的既有 requirement（进度链、守卫链、批 worker）不变；
     手动触发复用同一 checkpoint 入口与进度文件，仅在 checkpoint 上新增一个
     缺省关闭的授权旁路参数，属新增入口而非既有行为变更。 -->

## Impact

- `core/dashboard/routes/code_review_routes.py`：新增 2 个端点（fix-run 写信号 / fix-run-result 只读）。
- `fenixd.py`：主循环新增 `_check_code_fix_requests` 消费函数（1s 粒度扫描，读→删→调 checkpoint→写结果文件）。
- `core/code_fix.py`：`checkpoint()` 新增 `override_enabled` 参数（缺省 False，既有两路激活行为不变）。
- `core/dashboard/static/src/services/dashboard.ts`：新增 2 个 API 封装 + 结果类型。
- `core/dashboard/static/src/pages/projects/components/QualityTab.tsx`：按钮组新增「立即自动修复」+ 触发后轮询结果并 message 回显。
- `core/dashboard/static/dist/`：前端构建产物重建（npm run build，产物不入库、验证经主树 :8787 实时读盘）。
- 测试：`tests/test_dashboard_api.py`（路由端点）、`tests/test_code_fix.py`（checkpoint 旁路参数）、daemon 消费函数测试。
