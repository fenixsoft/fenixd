## Deliverables

```yaml
- path: core/agent_runner/harness/dsh_adapter.py
  kind: modify
- path: core/agent_runner/harness/claude_adapter.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: tests/test_harness_dsh_adapter.py
  kind: modify
- path: tests/test_harness_adapter.py
  kind: modify
- path: tests/test_harness_default_fallback.py
  kind: new
```

## 1. dsh 适配器回落路径

- [ ] 1.1 放宽 `build_spawn_spec` 三要素预检：`env_overrides` 完全无 provider 链键（baseurl/apikey 均空且 model 空的「无分配」形态）不再抛 `DshSpawnConfigError`，转落回落分支；含任一链键但三要素不全的形态保留报错（笔误防护）
- [ ] 1.2 回落分支实现：不写 patch 文件、argv 不携带 `--patch`；`build_env` 无 apikey 时不桥接 `FENIX_DSH_PROVIDER_API_KEY`；`--profile` 与反串扰环境清除语义不变
- [ ] 1.3 单测：无分配形态 argv/env 断言（无 `--patch`、无桥接键）、部分链形态仍报错、显式全链形态 spawn spec 与现行为逐字节一致

## 2. 对称 WARN 钩子与归因标记

- [ ] 2.1 进程级一次性 WARN：claude/dsh 两 adapter 回落形态生效时发一次「未分配 provider 链，回落 harness 默认配置」WARNING（进程×adapter 去重，锁纪律与 `get_current_adapter` 同型），不拒 spawn
- [ ] 2.2 run metrics 归因标记：回落 run 的 metrics 上下文写 `provider_source: "harness-default"`（显式链 run 无此键），读侧缺省兼容
- [ ] 2.3 单测：同进程 3 次回落 spawn 仅 1 条 WARNING；metrics 标记存在性两形态断言

## 3. 回归与验收

- [ ] 3.1 新建 `tests/test_harness_default_fallback.py` 覆盖 spec 三个 Requirement 全部 Scenario
- [ ] 3.2 既有 harness 测试全绿：`test_harness_dsh_adapter.py`/`test_harness_adapter.py`/`test_harness_claude_snapshot.py`/`test_harness_one_shot_forms.py`（快照零改动或仅注释级更新）
- [ ] 3.3 `test_dsh_full_chain.py`/`test_dsh_acceptance.py` 回归通过（显式链端到端形态不回归）
