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

- [x] 1.1 core/pm_engine/spec_review.py：新增 _artifact_landed_valid（读 .fenix/spec-review/<spec>/.fenix-run-result.json，校验 JSON 可解析、status ∈ {approved, repaired}、mtime ≥ 锚点写入（锚点 = 解析 entry.reviewer_run 内嵌 epoch 时间戳，即 dispatch_review 步骤①写入 run_id 的时刻，与 consume 内跳过的新鲜度校验语义同向）、snapshot spec 一致性（复用 _verify_snapshot 的 spec_files 删除硬门））
- [x] 1.2 run_spec_review 步骤 3 not run_ok 分支前置产物优先判定：合法 → warning 留痕（含 exit code 原因）+ consume_review_result + return True；不合法 → 既有 _handle_review_failure
- [x] 1.3 新增 _classify_run_failure(reason)→infra|content（在 _handle_review_failure 内对 reason 分类）：402/403/429/quota/budget/余额/rate limit → infra（大小写不敏感；reason 为 None/空时视为 content）；error **保留 spec-review-incomplete: 前缀**（spec_review.py:485 re_review startswith 契约），分类以 error 内后缀 [infra: <指纹>] 与告警 evidence 透出；本 SPEC 阶段 infra 仍按既有上限递增 _review_attempts（不递增语义由 run-failure-classification-circuitbreaker 承接，勿提前实现）

## 2. 测试

- [x] 2.1 tests/test_review_artifact_first.py：exit code 1 + 产物已落盘 approved → 走消费分支、_review_attempts 不递增、状态推进 ready
- [x] 2.2 产物缺失 / status=failed / 快照不一致 → 维持既有重试语义（attempt 递增）
- [x] 2.3 回放 1789368468 场景（402 + approved 产物）→ 不再抛掉结论
- [x] 2.4 tests/test_spec_review_agent.py：防回退——产物优先分支不得在 consume 后重派、不得重复消费