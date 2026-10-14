## Deliverables

```yaml
- path: core/dashboard/data/admin_actions.py
  kind: modify
- path: core/dashboard/data/adjudication_choices.py
  kind: modify
- path: core/pm_engine/verification/escalation.py
  kind: modify
- path: core/verdict_check.py
  kind: modify
- path: core/pm_engine/verification/pipeline.py
  kind: modify
- path: core/state_machine.py
  kind: modify
- path: tests/test_verify_env_handshake.py
  kind: modify
- path: tests/test_env_exemption_exit_reachability.py
  kind: modify
- path: tests/test_env_scenario_revision_exit.py
  kind: new
```

## 1. 豁免统一数据源（双门同源）

- [x] 1.1 core/dashboard/data/admin_actions.py：_exec_grant_env_exemption 豁免改以「场景 id+归一化失败签名+时效锚点」写入 spec 级 STATE 字段（新增结构常量单源定义；disposition 保留审计镜像）。
- [x] 1.2 core/verdict_check.py：whitewash_violations 逐项消费同一豁免源——命中有效豁免该项不计入 violations；保持 0-pass 不变量与 fail-closed（读失败=无豁免）。
- [x] 1.3 core/pm_engine/verification/escalation.py：_env_whitewash_gate 与握手消费同源锚点，消除「握手认可、门禁拒绝」矛盾（共享同一纯函数）。
- [x] 1.4 core/state_machine.py：豁免失效条件接入——场景定义变更（hash 变化）或时效过期即失效。

## 2. 场景修订重验出口

- [x] 2.1 core/dashboard/data/adjudication_choices.py：新增 revise_scenario_reverify 执行器——仅允许场景定义文件与夹具供给层路径（白名单校验，产品代码路径拒绝），复用规划车道出修订场景，修订次数上限默认 2。白名单路径以被验项目 project_root 锚定解析（拒绝绝对路径/穿越）；修订落盘同覆盖场景存储成对定义文件（test_scenarios.json 与 _scenarios_full.json）。
- [x] 2.2 core/pm_engine/verification/pipeline.py：修订重验生命周期——重验前从冻结集合摘除、修订 re-entry 先于升级、超限转人工冻结。豁免有效命中的 env 阻塞轮不计入 ENV_BLOCK_FREEZE_THRESHOLD，失效（TTL 过期/场景变更）后恢复计数。
- [x] 2.3 core/dashboard/data/admin_actions.py：env 归因证据要求——归因结论须附送帧/解码两段证据引用，缺失降级 inconclusive。

## 3. 测试

- [x] 3.1 tests/test_verify_env_handshake.py：双门一致性用例——有效豁免下握手与白化门禁同判放行；豁免失效（场景变更/过期）后同判拒绝；0-pass 场景不可白化不回退。
- [x] 3.2 tests/test_env_exemption_exit_reachability.py：既有 choices 闭环与时序用例不回退；豁免 STATE 字段写入/读取镜像一致。
- [x] 3.3 tests/test_env_scenario_revision_exit.py：修订出口全链——场景不可行→修订→重验→解冻；产品代码路径修订被拒；修订超限转人工；env 归因缺证据降级 inconclusive。