## Deliverables

```yaml
- path: agents/planner-judge.md
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: core/pm_engine/verification/verdict_evidence.py
  kind: modify
- path: core/verify_engine/judge_files.py
  kind: modify
- path: tests/test_env_attribution_gate.py
  kind: new
```

## 1. 归因证据门

- [x] 1.1 agents/planner-judge.md：env 定义段（约 65-66 行）改为要求「可复核环境量测（具体数值+来源）+ 验证窗口外对照样本」双要件，附「两轮同窗自测不构成对照」反例说明
- [x] 1.2 core/pm_engine/verification/verdict_evidence.py：`_handle_scenario_requeue`（:1213，条目构造约 :1287-1303）对将被置 accept 的 env 归因条目加证据校验（优先校验 measurement_refs/control_samples 非空，缺失回退查 attribution 文本量测数值与对照引用），校验不过按既有 requeue 状态落盘并注明缺失项，不落 accept；core/agent_runner/prompt_builder.py：`_scenario_classified`（:3303）辅门收紧——env 条目缺证据字段不视为「已归因存档」，截断恢复不沿用
- [x] 1.3 core/verify_engine/judge_files.py：条目 schema 契约补可选字段 measurement_refs 与 control_samples（save_attribution 键透传，读取侧缺字段按空处理向后兼容）；字段填充在 core/pm_engine/verification/verdict_evidence.py 条目构造侧完成；status 词表维持 ATTRIBUTION_STATUSES = accept/requeue 不变，不新增第三状态

## 2. 降级与复检接线

- [x] 2.1 core/pm_engine/verification/verdict_evidence.py：降级条目按 requeue 状态落盘即接入既有回炉重检闭环（build_requeue_manifest → 轻量重合成 judge run → 回灌校验链），确保不触发豁免握手、不以 env-accept 语义收尾；blocked-env 全批 inconclusive 通道（core/pm_engine/verification/escalation.py:402 `_handle_env_blocked_inconclusive`）语义不变

## 3. 测试

- [x] 3.1 tests/test_env_attribution_gate.py：覆盖「量测+对照齐全→accept 且新字段落盘」「缺量测或缺对照→requeue 落盘且不落 accept」「降级条目走回炉闭环、不触发豁免握手」「旧格式 judge_attribution.json 兼容读取」四场景