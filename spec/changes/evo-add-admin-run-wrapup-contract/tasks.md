## Deliverables

```yaml
- path: agents/administrator.md
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/agent_runner/liveness.py
  kind: modify
- path: tests/test_admin_wrapup_grace.py
  kind: new
```

## 1. 收尾宽限机制

- [ ] 1.1 core/agent_runner/runner.py：_turn_limit_action 末次扩容点（extension 2/2）对非 impl 车道（新增车道常量，与 IMPL_LANE_AGENT_TYPES 平行）且 run 内自建任务全部 completed 的 run 发放一次性收尾宽限（默认 20 轮，evidence 注记 wrapup_grace）；判据禁用 spec tasks.md 的 remaining_tasks；宽限耗尽走既有击杀路径。
- [ ] 1.2 core/agent_runner/liveness.py：_supervision_deadline_action 墙钟末次扩容同型收尾宽限，与轮数侧共用同一配置键。

## 2. 提示词硬契约

- [ ] 2.1 agents/administrator.md：追加硬终止契约——诊断闭环判定后先覆盖写最终处置记录再执行环境恢复/清理等长动作；自建任务全部 completed 后 MUST NOT 开启新一轮实验；最终处置记录不得留作最后一个动作。

## 3. 测试

- [ ] 3.1 tests/test_admin_wrapup_grace.py：覆盖末次扩容点触发收尾宽限、宽限耗尽落终态、自建任务未清零时不触发、impl 车道不受影响四类用例（邻位参考既有测试形态）。