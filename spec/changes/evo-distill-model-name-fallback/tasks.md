## Deliverables

```yaml
- path: core/knowledge.py
  kind: modify
- path: core/agent_runner/provider_circuit.py
  kind: reference
- path: tests/test_knowledge_distill_resume.py
  kind: modify
```

## 1. 显式模型与拒识兜底

- [ ] 1.1 core/knowledge.py：_spawn_and_wait（:1436-1494）spawn 恒传显式裸模型名（SpawnRequest.model→claude_adapter --model 透传链路已支持），配置为空时回退现行为并告警
- [ ] 1.2 core/knowledge.py：非零退出且 stderr 命中 [claude-code:unrecognized_model]（判别对照 core/agent_runner/provider_circuit.py:78-106 既有 pattern，只读复用不改语义）即以裸模型名自动重试一次，仍失败走既有 give_up→登台账路径且不重复登记

## 2. 台账龄期提醒

- [ ] 2.1 core/knowledge.py：基于 todo.md 重试行日期节计算登记龄期，超 24 小时未重试每日至多一条 admin 提醒（同日幂等），行被勾选/移除后停止

## 3. 测试

- [ ] 3.1 tests/test_knowledge_distill_resume.py：覆盖拒识命中→裸名单次重试成功、重试仍失败只登一次台账、显式 model 透传断言、龄期提醒触发与同日幂等