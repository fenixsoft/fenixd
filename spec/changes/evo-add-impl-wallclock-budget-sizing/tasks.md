## Deliverables

```yaml
- path: core/agent_runner/liveness.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/fast_track_result.py
  kind: modify
- path: core/config.py
  kind: modify
- path: tests/test_impl_wallclock_budget_sizing.py
  kind: new
```

## 1. 墙钟预算 sizing

- [ ] 1.1 core/fast_track_result.py：新增墙钟 sizing 配置读取与档位函数（仿 get_turn_budget_sizing_config :376 / suggested_turn_cap_for_scale :448 形状）：按 spec 规模输出 max_extensions 抬升档位，只抬不压、缺省向后兼容、STATE 覆盖键（impl_wallclock_extension_override）优先、关闭/非法值回退缺省。
- [ ] 1.2 core/agent_runner/liveness.py：_supervision_deadline_action（:1200-1330）接入 sizing 档位——泛化 :1249-1266 fast-track higher 档先例到 impl 车道抬 max_extensions；absolute_max_seconds 封顶语义不变；档位规模入参取启动同源总规模（estimate_spec_scale 单点，fast_track_result.py:152），逐 deadline 重算幂等、禁止以 remaining_tasks 回算档位。
- [ ] 1.3 core/config.py：SUPERVISION_DEFAULTS（:38-45）旁新增墙钟 sizing 缺省配置键；复核 supervision_floor（:2327）派生下限与抬升档位的协同。

## 2. 扩容判定纳入剩余任务数与用量注记

- [ ] 2.1 core/agent_runner/runner.py：超时收口（调用点 :5456-5458，kill 收口 :5481-5488 同源取数）向 _supervision_deadline_action 传入 remaining_tasks（新入参缺省 None，兼容门面委托 runner.py:602 与既有调用/测试），extend/kill evidence 携带；timeout_extension 事件（:5464-5471）同步携带（与 turn_extension 事件同型）。
- [ ] 2.2 core/agent_runner/runner.py：finally run_metrics 块（:5618-5705）在「击杀且无 CLI result」时附加用量缺失注记（原因＋transcript 字节数/轮数粗估维度），不臆造 cost；成功路径 :5730-5733 行为不变。
- [ ] 2.3 core/pm_engine/budget.py：复核 _is_exemptable_reason（:330-345）对「extension budget exhausted」的不可豁免口径在墙钟 sizing 生效后仍然成立。

## 3. 测试

- [ ] 3.1 tests/test_impl_wallclock_budget_sizing.py（新建）：sizing 归一化/只抬不压/阈值边界/覆盖键回退；扩容判定新分支（剩余任务非零优先扩容、预算耗尽击杀 evidence 带 remaining_tasks 且 reason 保留「extension budget exhausted」子串、absolute_max 仍封顶、档位幂等——推进中 remaining_tasks 递减不回撤已抬档位）；用量缺失注记（kill 无 result 落注记、成功路径不变）。
- [ ] 3.2 tests/test_impl_run_budget_sizing.py：既有 37 例全部不回退（轮数 sizing 语义零改动的回归证明）。