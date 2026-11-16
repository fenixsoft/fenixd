## Deliverables

```yaml
- path: agents/planner-judge.md
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: core/verify_engine/judge_files.py
  kind: modify
- path: tests/test_env_attribution_gate.py
  kind: new
```

## 1. 归因证据门

- [ ] 1.1 agents/planner-judge.md：env 定义段（约 65-66 行）改为要求「可复核环境量测（具体数值+来源）+ 验证窗口外对照样本」双要件，附「两轮同窗自测不构成对照」反例说明
- [ ] 1.2 core/agent_runner/prompt_builder.py：`_scenario_classified`（约 :3247）对 env 归因 accept 分支加证据校验（evidence 含量测数值与对照样本引用），校验不过改产 status=inconclusive 归因并注明缺失项，不落 accept
- [ ] 1.3 core/verify_engine/judge_files.py：judge_attribution.json 条目新增可选字段 measurement_refs 与 control_samples，accept 条目填充，读取侧缺字段按空处理（向后兼容）

## 2. 降级与复检接线

- [ ] 2.1 core/agent_runner/prompt_builder.py：inconclusive 归因条目接入既有 inconclusive_loop/recheck 通道（复用 core/alert_lifecycle.py 与 core/event_bus.py `_handle_env_blocked_inconclusive` 路径），确保不触发豁免握手、不以 env-accept 语义收尾

## 3. 测试

- [ ] 3.1 tests/test_env_attribution_gate.py：覆盖「量测+对照齐全→accept 且新字段落盘」「缺量测或缺对照→inconclusive 且不落 accept」「inconclusive 不触发豁免握手」「旧格式 judge_attribution.json 兼容读取」四场景