# Tasks: fix-admin-disposition-empty-shell

## Deliverables

```yaml
- path: core/agent_runner/runner.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: core/dashboard/static/src/pages/activities/index.tsx
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: modify
- path: tests/test_admin_disposition_failure_context.py
  kind: new
```

## 1. runner 失败日志

- [x] 1.1 `core/agent_runner/runner.py` `run_administrator`：`_run_claude` 异常路径（现有 `except Exception as e` 块，约 430-433 行）补充 `self.logger.warning("agent_runner", f"Administrator run {run_id} failed: {error}")`，级别 WARNING、component `agent_runner`、message 含 run_id 与异常文本

## 2. 落盘兜底与 error 字段

- [x] 2.1 `core/admin_monitor.py` `_invoke_administrator`（约 826-838 行）final disposition 落盘 dict 增加 `"error": disp.error or ""`
- [x] 2.2 同处对 `result == "failed"` 的记录做字段兜底：`recommended_action` 取 `disp.recommended_action or signal.get("recommended_action") or ""`；成功记录维持取 `disp.recommended_action` 现状不变；`description` 兜底语义不变

## 3. UI 展示失败原因

- [x] 3.1 `core/dashboard/static/src/pages/activities/index.tsx`：`ActivityCard` 支持 `a.error` 非空时在 body 顶部渲染失败原因行（danger 红色系、前缀「失败原因：」、PRE_WRAP），空 summary 兜底文案区同步附带 error 文本
- [x] 3.2 重建 dist 并提交产物（npm run build 于 `core/dashboard/static/`，产物随分支入库）

## 4. 测试与验证

- [x] 4.1 新增 `tests/test_admin_disposition_failure_context.py`：单测覆盖「CLI 失败 → final 记录含 error/兜底 recommended_action/description 非空」与「成功记录不受影响（无 error 键或空串）」两个分支；mock `_run_claude` 抛异常断言 WARNING 日志被调用
- [x] 4.2 全量 `python3 -m pytest tests/ -q` 通过，无回归
- [x] 4.3 合并后 touch `.fenix/restart_request` 优雅重启 daemon，确认新码生效（`ps` + 日志时间戳核对）

## 5. 端到端验证

- [x] 5.1 dashboard :8787 v3 运维记录页确认：存量空壳记录（无 error 键）渲染不报错；构造/等待一条带 error 的失败 disposition，卡片显示「失败原因：」行
