# 任务

## Deliverables

```yaml
- path: core/verify_contract.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: core/pm_engine/verification.py
  kind: modify
- path: tests/test_port_alignment.py
  kind: new
```

## 1. effective_port 解析输出

- [ ] 1.1 core/verify_contract.py：serve 解析时输出 effective_port（cmd 端口注入 / serve.port / 邻近扫描兜底），供 planner 注入与改写复用。

## 2. planner 上下文端口注入

- [ ] 2.1 core/agent_runner/prompt_builder.py：planner-judge prompt 注入「实际服务端口」段，场景 URL 必须基于注入端口生成。（原草稿写 .fenix/core/pm_engine/prompt_builder.py，主树无此文件——模块实际位置为 core/agent_runner/prompt_builder.py，已订正。）

## 3. 改写回写与臆测告警

- [ ] 3.1 core/pm_engine/verification.py：端口改写后写回 port_effective 到场景元数据，同窗口复用；port_rewrite_count ≥2 触发契约缺陷 WARNING。

## 4. 回归测试

- [ ] 4.1 tests/test_port_alignment.py：端口注入后 0 次改写；无契约改写 ≥2 次出 WARNING；改写后场景复用实际端口。
