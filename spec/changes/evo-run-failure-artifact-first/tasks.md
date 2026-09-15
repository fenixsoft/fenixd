## Deliverables

```yaml
- path: core/pm_engine/spec_review.py
  kind: modify
- path: tests/test_spec_review_agent.py
  kind: modify
- path: tests/test_review_artifact_first.py
  kind: new
```

## 1. 产物优先判定

- [ ] 1.1 core/pm_engine/spec_review.py：新增 _artifact_landed_valid（读 .fenix/spec-review/<spec>/.fenix-run-result.json，校验 JSON 可解析、status ∈ {approved, repaired}、mtime ≥ 锚点写入、snapshot spec 一致性）
- [ ] 1.2 run_spec_review 步骤 3 not run_ok 分支前置产物优先判定：合法 → warning 留痕（含 exit code 原因）+ consume_review_result + return True；不合法 → 既有 _handle_review_failure
- [ ] 1.3 新增 _classify_run_failure(reason)→infra|content：402/403/429/quota/budget/余额/rate limit → infra，error 前缀 spec-review-infra- 与告警 evidence 透出（不计入内容重试计数语义，完整熔断由 run-failure-classification-circuitbreaker 承接）

## 2. 测试

- [ ] 2.1 tests/test_review_artifact_first.py：exit code 1 + 产物已落盘 approved → 走消费分支、_review_attempts 不递增、状态推进 ready
- [ ] 2.2 产物缺失 / status=failed / 快照不一致 → 维持既有重试语义（attempt 递增）
- [ ] 2.3 回放 1789368468 场景（402 + approved 产物）→ 不再抛掉结论
- [ ] 2.4 tests/test_spec_review_agent.py：防回退——产物优先分支不得在 consume 后重派、不得重复消费