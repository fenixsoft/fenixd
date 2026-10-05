## Deliverables

```yaml
- path: agents/implementer.md
  kind: modify
- path: agents/administrator.md
  kind: modify
- path: core/agent_runner/result_gate.py
  kind: modify
- path: core/admin_store.py
  kind: modify
- path: tests/test_host_change_governance.py
  kind: new
```

## 1. 提示词契约

- [ ] 1.1 agents/implementer.md：约束节新增——宿主系统级变更（内核模块/dkms/系统包/设备节点）MUST 先备份原版本（路径+版本+加载参数）并在 run 结果登记；收工时变更仍在位 MUST 附回滚指引；能用户态解决的 MUST NOT 动系统级。
- [ ] 1.2 agents/administrator.md：处置记录模板将「备份目录/回滚计划」从示例升为破坏性动作 MUST 项。

## 2. 登记校验与回滚义务告警

- [ ] 2.1 core/agent_runner/result_gate.py：run-result 新增 host_changes 登记字段的警告级校验（fail-open，缺失不拒绝结果）。
- [ ] 2.2 core/admin_store.py：run 终态失败且 host_changes 非空时自动派发回滚义务告警（severity=major，含变更清单与回滚指引，去重键=spec+变更对象路径）；只告警不执行回滚。

## 3. 测试

- [ ] 3.1 tests/test_host_change_governance.py：覆盖 host_changes 校验 fail-open 语义、失败终态告警派发与去重、成功终态/无变更零告警。