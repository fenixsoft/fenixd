## Deliverables

```yaml
- path: core/admin_monitor.py
  kind: modify
- path: core/agent_runner/result_gate.py
  kind: modify
- path: agents/code-review.md
  kind: modify
- path: tests/test_code_review.py
  kind: modify
```

## 1. 零产物止损

- [ ] 1.1 core/admin_monitor.py：_run_code_review_checkpoint（:1710）在产物硬门拦截（零有效行/产物缺失）后自动重派审查 run 至多 1 次（限次常量仿 provider_circuit.py:76 的 RATELIMIT_REDISPATCH_MAX 先例），重派仍零有效行则发 admin 升级信号并停止重派
- [ ] 1.2 core/agent_runner/result_gate.py：_check_repo_code_review_artifact（:1182-:1200）拦截时透出失败面摘要（run id、manifest 计数、零有效行/产物缺失变体），供完成行与升级告警消费

## 2. 提示词自救指引

- [ ] 2.1 agents/code-review.md：预注工具自救指引段——ToolSearch 仅索引延迟加载工具，对 Bash/Read/Write/Grep 等基础工具返回 No matches 属按设计，直接调用即可，禁止凭「检索不到」推断工具缺失并放弃审查

## 3. 测试

- [ ] 3.1 tests/test_code_review.py：钉住「零有效行拦截→自动重派恰 1 次→重派仍失败→admin 升级信号且不再重派」链路（stub run 函数，不真实派发）
- [ ] 3.2 tests/test_code_review.py：断言审查提示词含自救指引关键句、升级告警携带失败面摘要字段