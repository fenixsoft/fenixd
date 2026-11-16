## Deliverables

```yaml
- path: core/pm_engine/verification/pipeline.py
  kind: modify
- path: core/worktree_manager/mergeback.py
  kind: modify
- path: tests/test_scenario_exec_tree_isolation.py
  kind: new
```

## 1. 执行树隔离

- [ ] 1.1 core/pm_engine/verification/pipeline.py：执行根决策点（:2707-2722 一带）为「无 serving worktree 条件且执行集含 pytest/cli 类场景」创建一次性快照 worktree 作为执行根（走 verify_engine/runner.py 既有 scenario_root 入参与产物准备路径），执行后清理；快照不可行时回退主树并留告警留痕。
- [ ] 1.2 同一决策点覆盖三缝：scenario-repaired 重入、排程重验（escalation.py:2770 入队后的执行）、unfreeze 重验均落隔离语义，不新增并行决策点。

## 2. 合回互斥

- [ ] 2.1 core/worktree_manager/mergeback.py：merge 启动前探测验证执行在飞（进程内信号优先，日志边沿兜底），在飞则有界等待/推迟，超时放行并告警留痕；不改变 WIP 重叠 precheck 既有语义。

## 3. 锚位稳态复跑

- [ ] 3.1 core/pm_engine/verification/pipeline.py：阶段2 聚合点（:2821 一带）对全量回归类场景的源码锚位类断言失败，自动对失败用例子集稳态复跑一次（一次为限），通过按瞬态留痕不计 fail，仍败按真实失败进入既有链路。

## 4. 测试

- [ ] 4.1 tests/test_scenario_exec_tree_isolation.py：覆盖①pytest/cli 执行集执行根落快照 worktree（模拟执行窗内主树被改写、断言结果不受影响）；②merge-back 在验证在飞时有界推迟、超时放行留痕；③锚位假失败稳态复跑甄别（复跑通过不计 fail、真失败仍 fail）；④回退主树路径留痕。