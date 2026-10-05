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

- [x] 1.1 core/verdict_check.py：triage_violation（:178）检测③（:231-242）返回违规前，由 step_results（success=false）/visual_results（diff_detected/warning）派生缺省 failed_assertions 清单（helper 置于 _scenario_has_failure_signal（:146-160）旁）；triage 覆盖校验改对派生清单核验——归因未逐条覆盖仍判违规并列出派生条目（fail-closed 不弱化），检测①②语义不动
- [x] 1.2 core/pm_engine/verification/verdict_evidence.py：_write_verdict_violations（:455）把派生清单注入重试提示，使重试轮 judge 直接拿到应申报条目；重试次数与 blocked 推进逻辑不变

## 2. 守卫测试

- [x] 2.1 tests/test_verdict_step_failure_shape.py（new）：仿 tests/test_verify_verdict_multi_kind.py 的 TestMultiKindTriageRequirement 风格补两例——assertion_results 空表+失败步骤+归因未覆盖派生清单→违规且文案含派生条目；归因逐条覆盖派生清单→合规
- [x] 2.2 tests/test_agent_prompt_files.py：断言 agents/planner-judge.md 含「步骤失败型场景必填清单」处方小节（fe612841 处方防漂移守卫；断言子串须与 agents/planner-judge.md:85 处方原文逐字一致，当前原文为「**步骤失败型场景必填清单（强制）**」）

## 验证修复（原地打回第 1 轮）

- [x] 先复核失败有效性：逐条核对 `spec/changes/evo-add-verdict-step-failure-evidence-derivation/verification-report.md` 中失败场景的期望断言（状态字面量/选择器/前置数据）与产品实际行为是否相符——断言与产品不符属场景缺陷，修场景文件；确属产品行为不符才修产品代码（结论：产品 Bug——场景期望裸专名 probe-visual-gamma 归因合规与 design 风险节「以名称对应归因」契约相符；产品把自造 visual: 前缀整串当唯一对账 token 属假阴性）
- [x] 按复核结论修复：场景缺陷改场景文件，真实产品 Bug 改产品代码（core/verdict_check.py _derived_label_tokens 对视觉派生条目剥 visual: 前缀补裸名别名 token；tests/test_verdict_step_failure_shape.py 补裸名归因合规/完整前缀仍合规/无关归因仍违规三例守卫）
- [x] 修复后重跑验证确认通过（verdict 相关 26 个测试文件定向回归全绿：5 文件 176 passed + 21 文件 456 passed/1 xfailed，含复刻 BUG-01 失败形态的 test_visual_bare_name_attribution_compliant）
