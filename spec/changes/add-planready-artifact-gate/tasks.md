# Tasks: add-planready-artifact-gate

## Deliverables

```yaml
- path: core/agent_runner/runner.py
  kind: modify
- path: core/pm_engine/verification.py
  kind: modify
- path: core/verify_report.py
  kind: modify
- path: core/dashboard/static/src/pages/projects/detail.tsx
  kind: modify
- path: tests/test_planready_artifact_gate.py
  kind: new
```

## 1. planner-plan 产物硬门扩展（G1/G2，design D1/D2）

- [x] 1.1 `core/agent_runner/runner.py` `_check_agent_result_artifact`：planner-plan 分支在既有 test_scenarios.json 校验之上叠加 `.fenix-run-result.json` 校验——路径经 `planner_result_path(self.project_root, spec_name, "planner-judge")` 同源计算；校验存在/非空/合法 JSON/顶层对象/status ∈ `("plan-ready",)`；mtime 新鲜度守卫与 test_scenarios.json 同规则（`run_started_at` 宽限期）；任一不满足返回含具体文件路径与原因类别的失败文案；同步更新 `AgentArtifactGateError` docstring（plan 类型也含结果文件契约）与旧注释「planner-plan 无 status 契约」
- [x] 1.2 `tests/test_planready_artifact_gate.py`：覆盖 spec 四 Scenario——未写结果文件拦截+走退避重试通道（`AgentArtifactGateError` 断言）、status='success' 白名单外拦截且文案含真实取值、双产物齐备放行（返回 None）、结果文件 mtime 陈旧残留拦截；另覆盖健康 plan-ready 文件+场景文件任一缺失时的组合行为

## 2. 降级上下文落盘与合成报告标注（G3，design D3/D4）

- [x] 2.1 `core/pm_engine/verification.py` 阶段1 降级判定点：降级前写 `.fenix/verify-progress/<spec>/degrade_context.json`（reason=归因文案、run_id、duration_seconds、cost_usd、degraded_at UTC ISO）；写失败不阻断降级主流程（WARNING 留痕）；新验证流程成功路径（plan-ready 校验通过后）删除陈旧 degrade_context.json（防污染后续正常报告）
- [x] 2.2 `core/verify_report.py` `synthesize_verification_report`/`render_verification_report`：合成时读 degrade_context.json，report.json 顶层注入 `degrade_annotation` 字段（reason/run_id/duration_seconds/cost_usd/degraded_at）持久化，verification-report.md 头部渲染「⚠️ 降级说明」引用块（含原因+run_id+分钟+美元）；无 degrade_context.json 时零注入零渲染（正常报告不含该字段）
- [x] 2.3 `core/dashboard/static/src/pages/projects/detail.tsx` 验证报告区：条件渲染降级标注一行提示（数据源自报告 degrade_annotation 字段），无字段不渲染
- [x] 2.4 `tests/test_planready_artifact_gate.py` 扩展：降级合成报告携带标注三 Scenario（降级标注持久化 report.json + markdown 渲染、正常报告无字段、degrade_context 缺失时合成行为不变）；pm_engine 侧降级判定点写文件与新流程成功删文件的分支覆盖

## 3. 收尾验证

- [x] 3.1 全量跑 `tests/test_planready_artifact_gate.py` + 既有 `tests/test_agent_runner_gate.py`、`tests/test_verify_report_gate.py` 无回归；标注真实生效路径：模拟 planner 未写结果文件 → 硬门拦截 → 重试 → 仍失败 → 降级 → 合成报告含降级标注（单测集成路径或本地脚本演练，截图/输出存 .history）
- [ ] 3.2 合并后重启 daemon（supervisor 协议），确认新码生效（进程代码版本核对）——2026-09-09 事故第 4 层根因（旧码运行）的收尾防线
