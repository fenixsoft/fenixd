## Deliverables

```yaml
- path: core/agent_runner/runner.py
  kind: modify
- path: tests/test_agent_runner_gate.py
  kind: modify
```

## 1. 派发前留档

- [ ] 1.1 core/agent_runner/runner.py：run_planner 的 mode=="judge" 分支在派发前将已存在的 .fenix/verify-progress/<spec>/.fenix-run-result.json 原子改名为 prev-judge-result.json（仿 core/pm_engine/family.py prev-impl-result.json 先例；改名失败仅 WARNING 不阻断派发；不触碰 report.json/tokens.json 等跨轮产物）。
- [ ] 1.2 core/agent_runner/runner.py：_handle_artifact_gate_retry 命中陈旧残留（artifact-structural）进入原地重试前，先改名/删除该陈旧文件，使再败归因退化为「结果文件缺失」并防烧光重试预算。仅限 agent_type=="planner-judge" 且路径经 planner_result_path(root, spec, "planner-judge") 重建（MUST NOT 解析 error 归因文案取路径）；该通道全 agent_type 通用，跨 spec 共享根文件 .fenix/.fenix-run-result.json 及其他 agent_type 产物不得改名/删除。

## 2. 测试

- [ ] 2.1 tests/test_agent_runner_gate.py：新增用例——预置陈旧结果文件后 run_planner(spec,"judge") 派发前文件已改名、本轮硬门放行、prev-judge-result.json 内容可回溯；无遗留文件时派发行为零变化；改名失败不阻断派发；陈旧残留重试不再重复命中同一陈旧文件。