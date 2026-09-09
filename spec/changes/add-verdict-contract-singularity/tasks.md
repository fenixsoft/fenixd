# Tasks: add-verdict-contract-singularity

## Deliverables

```yaml
- path: tests/test_verdict_contract_singularity.py
  kind: new
```

## 1. 同源锚定测试

- [ ] 1.1 tests/test_verdict_contract_singularity.py（new）：读 `agents/planner-judge.md` 源文本，从 `core.verdict_check` 导入常量（VERDICT_CLASSES / NON_PASS_STATUSES / FORCE_FAILED_CLASSES），按「取值逐字出现」断言一致性；失败消息携带常量名与缺失取值
- [ ] 1.2 证据结构锚定：evidence 三维度键名（failed_assertions / screenshots / first_failed_step）与 assertion_triage 条目字段（assertion / classification / evidence）在 prompt 结构定义中出现
- [ ] 1.3 哨兵用例：prompt 分类定义段作为合法分类推荐的取值不超出 VERDICT_CLASSES（防未注册分类值）

## 2. 回归验证

- [ ] 2.1 对 planner-judge.md 做一次无害措辞微调演练（不影响锚定取值），断言测试通过（tolerate 无害文案变化）；对 verdict_check 常量做临时改动演练，断言测试红（双向覆盖）
- [ ] 2.2 既有测试全绿：test_verdict_evidence_taxonomy.py、test_judge_efficiency.py 无回归
