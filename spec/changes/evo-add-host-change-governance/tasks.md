## Deliverables

```yaml
- path: agents/implementer.md
  kind: modify
- path: agents/administrator.md
  kind: modify
- path: core/agent_runner/result_gate.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/admin_store.py
  kind: modify
- path: tests/test_host_change_governance.py
  kind: new
```

## 1. 提示词契约

- [ ] 1.1 agents/implementer.md：约束节新增——宿主系统级变更（内核模块/dkms/系统包/设备节点）MUST 先备份原版本（路径+版本+加载参数）并**在变更发生时即时写入 worktree 根 host_changes.json 登记文件**（收尾在 run 结果汇总，两处一致）；收工时变更仍在位 MUST 附回滚指引；能用户态解决的 MUST NOT 动系统级。
- [ ] 1.2 agents/administrator.md：处置记录模板将「备份目录/回滚计划」从示例升为破坏性动作 MUST 项。

## 2. 登记载体、终态派发与校验

- [ ] 2.1 core/agent_runner/runner.py：worktree 根 host_changes.json 加入 `_copyback` 拷回清单；终态记录段（覆盖 error/killed/超时/轮次上限/判停，先于 worktree 清理）读取登记文件，失败终态且登记非空时调用 admin_store 派发，成功终态仅留痕。
- [ ] 2.2 core/admin_store.py：新增回滚义务告警派发方法（severity=major，kind=escalation，append_if_absent 去重键=spec+变更对象路径，含变更清单与回滚指引），由 runner 终态路径调用；只告警不执行回滚。
- [ ] 2.3 core/agent_runner/result_gate.py：run-result host_changes 汇总字段的警告级校验（fail-open，缺失不拒绝结果）。

## 3. 测试

- [ ] 3.1 tests/test_host_change_governance.py：覆盖击杀类终止（无 run-result）时读 worktree 根登记文件派发告警、host_changes 汇总校验 fail-open 语义、失败终态告警派发与去重、成功终态/无登记文件零告警。