## Deliverables

```yaml
- path: core/code_fix.py
  kind: modify
- path: core/dashboard/routes/code_review_routes.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/pages/projects/components/QualityTab.tsx
  kind: modify
- path: tests/test_code_fix.py
  kind: modify
- path: tests/test_code_fix_manual_trigger.py
  kind: new
- path: tests/test_dashboard_api.py
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. checkpoint 临时授权参数

- [x] 1.1 `core/code_fix.py` 的 `CodeFixOrchestrator.checkpoint()` 新增 `override_enabled: bool = False` 参数：为 True 时跳过 enabled 守卫（其余守卫——单飞/无 open 条目/失败保留/回归契约 fail-closed——原样生效），缺省 False 时行为与现状逐字节一致
- [x] 1.2 `tests/test_code_fix.py` 补三类用例：override_enabled=True 且 enabled=false 时投递成功；override_enabled=True 下 already_running / 回归契约缺失仍拒绝；不传参数（两路后台激活形态）在 enabled=false 时仍不投递

## 2. dashboard 信号端点与 API 封装

- [x] 2.1 `core/dashboard/routes/code_review_routes.py` 新增 `POST /api/code-review/fix-run`（注册进 base.py 路由表；project 取自 query，经 `_project_from_query`，对齐 `_api_code_review_run` 形态）：项目 404 / daemon stopped 400 / unmanaged 409 前置拦截（对齐 `_api_code_review_run` 的 `hosting_state` 判据）；通过后预删旧结果文件、`O_CREAT|O_EXCL` 原子写 `.fenix/code_fix_request.json`（payload `{source: "dashboard", created: <UTC ISO>}`），FileExistsError → 409；返回 `{ok, requested_at}`
- [x] 2.2 同文件新增 `GET /api/code-review/fix-run-result?project=`（注册进 base.py）：只读返回 `.fenix/code_fix_request_result.json` 内容，缺失返回缺省态 `{}`（MUST NOT 500，形态对齐 `_api_code_review_fix_progress`）；`core/dashboard/data` 层补对应读取函数
- [x] 2.3 `core/dashboard/static/src/services/dashboard.ts` 新增 `triggerCodeFixRun(project)` 与 `getCodeFixRunResult(project)` 封装及结果类型（含 `request_created/triggered/reason/message/finished_at`）

## 3. daemon 消费与结果反馈

- [x] 3.1 `fenixd.py` 新增 `_check_code_fix_requests`：主循环 1s 粒度扫描 `.fenix/code_fix_request.json`，先读后删（读/删失败跳过本轮），经 `getattr(agent_runner, "_code_fix_orchestrator", None)` 取编排器（未装配 → 落 `orchestrator_missing` 结果），以 `override_enabled=True` 调 `checkpoint()`，无论 triggered 与否原子写结果文件 `{request_created, triggered, reason, message, finished_at}`（reason→中文 message 映射一处收口；checkpoint 异常落 `dispatch_exception` 结果）；在主循环既有信号扫描处挂载调用
- [x] 3.2 新建 `tests/test_code_fix_manual_trigger.py`：消费函数用例覆盖——开关关闭仍投递（临时授权）、already_running/no_open_items/回归契约缺失三类拒绝的结果文件内容、orchestrator 缺失不静默、结果文件 `request_created` 回链信号 `created`、信号先读后删（异常不复活）

## 4. 前端按钮与原因回显

- [x] 4.1 `QualityTab.tsx` 动作按钮组新增「立即自动修复」按钮（全仓库审查/当期提交审查之后，默认样式与相邻触发按钮一致）：点击调 `triggerCodeFixRun`，受理后 1s 间隔轮询 `getCodeFixRunResult`（上限 20s），仅认 `request_created === 本次 requested_at` 的结果，按 `triggered` 弹成功/拒绝原因 message；超时弹「请稍后在进度卡片或 daemon 日志确认」；pending/loading 门控防连点；触发成功不额外操作（CodeFixProgressCard 既有轮询自动接管进度展示）
- [x] 4.2 `npm run build` 通过，主树 dist 产物更新（验证经主树 :8787 实时读盘）

## 5. 路由测试与全量回归

- [x] 5.1 `tests/test_dashboard_api.py` 补端点用例：fix-run 受理 200 写信号、并发/残留 409、项目 404、stopped/unmanaged 前置拦截、fix-run-result 缺省态与内容透传
- [x] 5.2 `pytest tests/test_code_fix.py tests/test_code_fix_manual_trigger.py tests/test_dashboard_api.py tests/test_code_review.py` 全绿
