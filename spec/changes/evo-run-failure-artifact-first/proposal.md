# run-failure-artifact-first — 评审失败判定先查已落盘产物

## Why

2026-09-14 14:56 事故：run spec-review-evo-item-retention-doc-tracking-1789368468 在 .fenix/spec-review/evo-item-retention-doc-tracking/.fenix-run-result.json 落盘 status=approved（5 findings 全 note、无阻断）后仅 17 秒，run 因转录尾部「API Error: 402 余额不足」以 Exit code 1 被判失败；approved 结论未消费、_review_attempts 直接递增至 3 次上限后冻结，$6.24 + $2.30（合计 $8.54）付费评审作废，spec 15:45 重立后评审重来。

根因：run 成败由 CLI exit code 一票判定（spec_review.py run_spec_review 步骤 3 run_ok=result.success，not run_ok 即 _handle_review_failure 重试），产物是否已合法落盘不作为判败前置条件——「产物已具备却被退出码一票否决」。

## What Changes

- 评审 run 判定失败前先校验 .fenix/spec-review/<spec>/.fenix-run-result.json 是否合法落盘（status ∈ {approved, repaired}、mtime 不早于本次 run 锚点写入、与派发前快照 spec 一致性）；合法 → 按产物消费（consume_review_result），exit code 失败仅降级为 warning 日志并留痕，不递增 _review_attempts、不重派。
- 失败原因识别 infra 指纹（402/403/quota/budget/余额/rate limit），标记失败分类为 infra 并写入 error 前缀与告警 evidence，不计入内容质量重试语义（完整熔断冷却由 run-failure-classification-circuitbreaker 承接；本 SPEC 只做产物优先判定与 infra 识别标记）。
- 车道范围：本 SPEC 先钉 spec-review 车道（事故现场），验证/实现车道按同一模式后续扩展。

## 验收

- 回放 1789368468：exit code 1 + 结果文件已落盘 approved → 消费产物、状态推进、_review_attempts 不递增。
- 结果文件缺失 / status=failed / 快照不一致 → 维持既有重试语义（attempt 递增）。
- 单测覆盖两分支 + 防回退（不得在 consume 后重派、不得重复消费）。