## Deliverables

```yaml
- path: core/verdict_check.py
  kind: modify
- path: core/pm_engine/verification/verdict_evidence.py
  kind: modify
- path: tests/test_verdict_step_failure_shape.py
  kind: new
- path: tests/test_agent_prompt_files.py
  kind: modify
```

## 1. 证据派生

- [ ] 1.1 core/verdict_check.py：triage_violation（:178）检测③（:231-242）返回违规前，由 step_results（success=false）/visual_results（diff_detected/warning）派生缺省 failed_assertions 清单（helper 置于 _scenario_has_failure_signal（:146-160）旁）；triage 覆盖校验改对派生清单核验——归因未逐条覆盖仍判违规并列出派生条目（fail-closed 不弱化），检测①②语义不动
- [ ] 1.2 core/pm_engine/verification/verdict_evidence.py：_write_verdict_violations（:455）把派生清单注入重试提示，使重试轮 judge 直接拿到应申报条目；重试次数与 blocked 推进逻辑不变

## 2. 守卫测试

- [ ] 2.1 tests/test_verdict_step_failure_shape.py（new）：仿 tests/test_verify_verdict_multi_kind.py 的 TestMultiKindTriageRequirement 风格补两例——assertion_results 空表+失败步骤+归因未覆盖派生清单→违规且文案含派生条目；归因逐条覆盖派生清单→合规
- [ ] 2.2 tests/test_agent_prompt_files.py：断言 agents/planner-judge.md 含「步骤失败型场景必填清单」处方小节（fe612841 处方防漂移守卫；断言子串须与 agents/planner-judge.md:85 处方原文逐字一致，当前原文为「**步骤失败型场景必填清单（强制）**」）