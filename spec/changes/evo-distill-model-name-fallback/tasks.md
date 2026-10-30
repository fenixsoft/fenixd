## Deliverables

```yaml
- path: core/knowledge.py
  kind: modify
- path: core/config.py
  kind: modify
- path: core/agent_runner/provider_circuit.py
  kind: reference
- path: tests/test_knowledge_distill_resume.py
  kind: modify
```

## 1. 显式模型与拒识兜底

- [ ] 1.1 core/config.py + core/knowledge.py：新增 `knowledge.model` 配置键（蒸馏车道现状无模型配置键；ConfigLoader 回退必告警口径），_spawn_and_wait（实测 :1470-1528）spawn 恒传显式裸模型名（SpawnRequest.model→claude_adapter :377-378 --model 透传链路已支持），未配置/非法/空值回退现行为（不传）并告警
- [ ] 1.2 core/knowledge.py：非零退出且 stderr 命中 [claude-code:unrecognized_model]（判别对照 core/agent_runner/provider_circuit.py:86-89 既有 UNRECOGNIZED_MODEL_TEXT_PATTERNS 裸子串形态，只读复用不改语义）时，仅当本次未显式传 model（生效模型名为宿主别名解析产物）才以裸模型名自动重试一次；显式传名仍被拒为确定性失败（同因重试必然再拒），不重试；两种收场均走既有 give_up→登台账路径且不重复登记，台账 reason 注明拒识形态与生效模型名

## 2. 台账龄期提醒

- [ ] 2.1 core/knowledge.py：基于 todo.md 重试行日期节计算登记龄期，超 24 小时未重试每日至多一条 admin 提醒——经 AdminStore.append(kind=SIGNAL)（先例 core/code_fix.py:3434）发出，同日幂等以 daemon 进程内当日标记承载；扫描挂 daemon 周期维护循环触发（不得仅依赖新失败顺带扫描），dashboard --serve 不接入；行被勾选/移除后停止

## 3. 测试

- [ ] 3.1 tests/test_knowledge_distill_resume.py：覆盖拒识命中（未显式传名）→裸名单次重试成功、重试仍失败只登一次台账、显式传名仍被拒→不重试直接 give_up 且台账注明生效模型名、显式 model 透传断言、knowledge.model 缺省/空值回退不传名并告警、龄期提醒触发与同日幂等（含无新失败时周期扫描仍触发）