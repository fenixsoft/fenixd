## Deliverables

```yaml
- path: agents/implementer.md
  kind: modify
- path: agents/planner-plan.md
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/config.py
  kind: modify
- path: tests/test_impl_env_blocker_stop_loss.py
  kind: new
```

## 1. 提示词止损硬规则

- [ ] 1.1 agents/implementer.md：约束段追加——同一环境依赖连续 ≥3 次失败尝试（按尝试计数，不按错误签名）即冻结该任务，design 有 fallback 先走 fallback，否则登记 unfinished 转 partial 继续；MUST NOT 为救单个验证场景对宿主做内核级/镜像级不可逆改造。
- [ ] 1.2 agents/planner-plan.md：环境依赖类任务在任务书标注「环境依赖、有/无 fallback」类别，与止损规则联动。

## 2. 进度停滞观测面

- [ ] 2.1 core/agent_runner/runner.py：impl run 轮询路径增加「自最近 run 内任务完成起的轮数」计数（复用 core/run_task_track.py 流内解析单点），超阈值时 run_metrics 注记+WARNING；观测不参与续期/击杀判定。
- [ ] 2.2 core/config.py：新增停滞预警配置键（阈值/开关），沿既有 agents.run_stall_budget_* 键风格归一化，缺省开启、可关闭。

## 3. 测试

- [ ] 3.1 tests/test_impl_env_blocker_stop_loss.py：覆盖止损规则提示词文本契约、失败尝试计数与停滞预警触发、观测不改变续期/击杀判定、既有预算 sizing 行为不回退。