## Deliverables

```yaml
- path: core/admin_monitor.py
  kind: modify
- path: core/agent_runner/result_gate.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: agents/code-review.md
  kind: modify
- path: tests/test_code_review.py
  kind: modify
```

## 1. 零产物止损

- [ ] 1.1 core/admin_monitor.py：_run_code_review_checkpoint（:1720）在产物硬门拦截（零有效行/产物缺失）后自动重派审查 run 至多 1 次（限次常量仿 provider_circuit.py:76 的 RATELIMIT_REDISPATCH_MAX 先例，限次口径为 monitor 生命周期合计、与 429 重派通道同款），重派仍零有效行则经既有 admin 升级记录通道（admin-dispatch-failure-escalation D1/D2 先例）发升级信号并停止重派；与 429 重派通道互不叠加调度同一 run 链
- [ ] 1.2 core/agent_runner/result_gate.py：_check_repo_code_review_artifact（:1141-:1232）拦截时透出失败面摘要（run id、manifest 计数、零有效行/产物缺失变体），供完成行与升级告警消费；调用方 core/agent_runner/maintenance_runs.py gate_err 分支（:2131）同步消费新结构

## 2. 提示词自救指引

- [ ] 2.1 agents/code-review.md：预注工具自救指引段（6dc7 并入的完整纪律）——① ToolSearch 仅索引延迟加载工具，对 Bash/Read/Write/Grep 等基础工具返回 No matches 属按设计，直接调用即可；② 工具存在性以 select: 精确名探测；③ 工具面确认缺失时按 TOOLFACE-MISSING fail-fast；禁止凭「检索不到」推断工具缺失并放弃审查

## 3. 测试

- [ ] 3.1 tests/test_code_review.py：钉住「零有效行拦截→自动重派恰 1 次→重派仍失败→admin 升级信号且不再重派」链路（stub run 函数，不真实派发），并钉住零产物与 429 两通道限次合计语义、互不叠加调度
- [ ] 3.2 tests/test_code_review.py：断言审查提示词含自救指引关键句（按 tests/test_prompt_lane_efficiency_sections.py 先例做契约测试，钉住纪律三要素：基础工具直调 / select: 精确名探测 / TOOLFACE-MISSING fail-fast）、升级告警携带失败面摘要字段
- [ ] 3.3 tests/test_code_review.py：钉住「error 收场终局结论行抢救不触发全仓快照核销与 code-fix 检查点」红线、工具预检与 run_metrics 工具面字段

## 4. spawn 后写工具预检（6dc7 并入增量①）

- [ ] 4.1 core/agent_runner/runner.py：spawn 后写工具预检——agent_runner 全仓现无 allowedTools 预检（grep 零命中，2026-10-30 人工核查），spawn 装配（claude CLI 子进程装配点）后做一次工具面预检并留痕，预检结果进失败面摘要与 run_metrics 收尾

## 5. 终局消息结论行抢救（6dc7 并入增量②）

- [ ] 5.1 core/agent_runner/maintenance_runs.py：error 收场段（:2330-:2356）现只读 shard_paths/主产物文件，终局消息结论行丢失——补终局消息结论行抢救，红线与既有抢救一致：MUST NOT 触发全仓快照核销与 code-fix 检查点

## 6. run_metrics 工具面留痕（6dc7 并入增量③）

- [ ] 6.1 core/agent_runner/runner.py：run_metrics 收尾（_log_run_metrics，:1400）补工具面字段留痕（预检结果、TOOLFACE-MISSING 分类等），供事后取证
