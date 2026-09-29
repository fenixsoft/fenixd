<!-- knowledge: capability=run-failure-judgment rev=1 sources=spec/archive/2026-09-21-evo-run-failure-artifact-first -->

# run 失败判定（产物优先）

评审 run 失败时先查已落盘产物再判失败：产物合法即消费推进，不以退出码论死活；父级 run 失败不据以派生 fix 链。

## 现行规则

- 产物优先：spec-review run 以非零 exit code 收工、但 `.fenix/spec-review/<spec>/.fenix-run-result.json` 已合法落盘时，按产物消费（approved → ready；repaired → repair 通道），退出码仅降级 warning 日志 + 告警留痕；`_review_attempts` 不递增，不重派评审。
- 产物「合法」的充分条件：文件存在、JSON 可解析、`status ∈ {approved, repaired}`、mtime 不早于本次 run 锚点（`reviewer_run`）写入时刻、与派发前快照（snapshot.json）的 spec 一致性校验通过。
- 消费幂等：consume 后 `reviewer_run` 清空，不触发重派。
- 产物缺失/非法（内容失败）：维持既有语义——`_handle_review_failure` 递增 `_review_attempts` 至上限（3）后 `freeze_for_human`。
- infra 识别与标记：失败原因文本匹配 infra 指纹（402/403/429/quota/budget/余额/insufficient balance/rate limit）时，本次 run 失败分类标记为 infra 并随 error/告警 evidence 透出，提示上层走 infra 处置，不计入内容质量重试计数（熔断/冷却由 run-failure-classification 承接）。
- 父级 run 失败按伪失败裁决，不据此派生 fix 链；派生判定须基于合入后的真实验证报告。
- 边界：评审内容质量门（approved 须 findings 无阻断、repairs 一致性等既有硬门，`consume_review_result` 内校验）与 verifier 结果读取单源均不变。

## 溯源

- 史前复原 — 迁移期基线：父级 run 失败按伪失败裁决，不据此派生 fix 链；派生判定须基于合入后的真实验证报告
- [2026-09-21 evo-run-failure-artifact-first](spec/archive/2026-09-21-evo-run-failure-artifact-first/) — 确立评审失败的产物优先消费与合法性五条件、infra 指纹识别标记、内容失败既有通道不变
